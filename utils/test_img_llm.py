"""
大模型链接分别使用下面两个:
llm_model_params:
  model_name: 'doubao-1-5-pro-32k-250115'
  base_url: "https://ark.cn-beijing.volces.com/api/v3"
  api_key: '48f15b1a-430e-4977-99f6-2b3482a8cf65'

llm_model_params:
 model_name: 'qwen3.6-35b-a3b-fp8'
 base_url: "http://10.0.0.214:8088/v1"
 api_key: "gpustack_94b5249db8eafa52_676197051c8790cf7b3c35dabf0d49d1"


测试视觉模型:
qwen3.8-max
doubao-seed-2-1-pro
glm-5v-turbo
qwen3.7-plus
qwen3.5-397b-a17b
qwen3.8-27b
qwen3.6-35b-a3b


测试图片:
图片名称正常的名称带normal, 异常的带有error, 下面文件夹有三组图片.
./test_imgs/001
./test_imgs/002
./test_imgs/003


实现逻辑:
扫描图片
   ↓
识别 normal / error
   ↓
调用 7 个模型
   ↓
每张图片重复 10 次
   ↓
保存原始 JSON
   ↓
自动计算 Accuracy / Recall / F1
   ↓
计算 FP / FN
   ↓
计算 10 次稳定性
   ↓
计算延迟
   ↓
生成 CSV / Excel
   ↓
生成最终模型排名

评估市面主流多模态大模型的视觉识别、正常/异常判断及故障识别能力，重点面向故障报修场景。
使用大模型测试准确率, 识别正常和异常的情况, 先只看结果里面正常异常识别对不对, 然后统计汇总这几个模型识别的准确率, 每个模型每张图跑10次, 看稳定性.

记录执行时长, 和返回的文字, 保存到 CSV 文件中.

1 调整下, Qwen模型统一使用 dashscope
2 先测试 大模型API是否能联通
调整代码, 使用多进程调用, 如果反复10次也同时调用, 多个模型也同时调用.
"""

import base64
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from dynaconf import Dynaconf
from openai import OpenAI


# ============================================================
# 路径配置
# ============================================================
SCRIPT_DIR = Path(__file__).resolve().parent
TEST_IMGS_DIR = SCRIPT_DIR / "test_imgs"
RESULTS_DIR = SCRIPT_DIR / "results"
RAW_JSON_DIR = RESULTS_DIR / "raw_json"

# ============================================================
# 测试参数
# ============================================================
NUM_RUNS = 10    # 10     # 每张图片重复调用次数
MAX_RETRIES = 3
RETRY_DELAY = 2
CALL_INTERVAL = 0.5

# ============================================================
# 模型端点配置
# ============================================================

key_settings = Dynaconf(
    settings_files=['../basic_config/key_settings.yaml'],
)
print(F'key_settings["doubao"]: {key_settings["doubao"]}')

ENDPOINTS = {
    "doubao": key_settings["doubao"],
    "dashscope": key_settings["dashscope"],
    "zhipu": key_settings["zhipu"],
}

# ============================================================
# 待测模型列表
#   name: 模型名称（API 调用时的 model 参数）
#   endpoint: 对应 ENDPOINTS 中的 key
#   use_thinking_control: 是否传 extra_body 关闭思考模式（vLLM 部署的 Qwen 模型需要）
# ============================================================
MODELS = [
    {"name": "qwen3.8-max", "endpoint": "dashscope", "use_thinking_control": False},
    {"name": "doubao-seed-2-1-pro-260628", "endpoint": "doubao", "use_thinking_control": False},
    # {"name": "glm-5v-turbo", "endpoint": "zhipu", "use_thinking_control": False},
    {"name": "qwen3.7-plus", "endpoint": "dashscope", "use_thinking_control": False},
    {"name": "qwen3.5-397b-a17b", "endpoint": "dashscope", "use_thinking_control": False},
    # {"name": "qwen3.8-27b", "endpoint": "dashscope", "use_thinking_control": False},
    {"name": "qwen3.6-27b", "endpoint": "dashscope", "use_thinking_control": False},
    {"name": "qwen3.6-35b-a3b", "endpoint": "dashscope", "use_thinking_control": False},
]

# ============================================================
# 提示词
# ============================================================
SYSTEM_PROMPT = """/no_think
你是水务厂区巡检视觉识别助手。请判断监控画面中是否存在异常：
1. 漏液：地面或设备表面出现液体渗漏、滴落、扩散浸润的痕迹（水、油、药剂等）；
2. 漏墨：出现墨水类物质泄漏（通常为蓝/紫/红等颜色的墨迹残留）。
3. 是否发生堆料, 如果堆积物堵到了排泥阀的管口就是发生了堆料
4. 水泵是否发生了漏水, 如果水泵周围有漏水, 就是发生了漏水

请严格按以下格式返回：
【结论】异常 / 正常
【异常类型】漏液 / 漏墨 / 无
【判断依据】简要说明画面中支持该结论的视觉特征（位置、颜色、形态）。
"""

USER_PROMPT = "请判断这张监控图片是否异常（是否有漏液、漏墨、堆料、漏水），并给出判断依据。"


# ============================================================
# 数据结构
# ============================================================
@dataclass
class ImageItem:
    path: Path
    group: str
    ground_truth: str  # "normal" 或 "error"


@dataclass
class RunResult:
    model_name: str
    image_group: str
    image_name: str
    ground_truth: str
    run_index: int
    raw_response: str
    parsed_result: str  # "正常", "异常", "unknown"
    is_correct: bool
    latency: float
    timestamp: str
    error: str = ""


# ============================================================
# 图片扫描
# ============================================================
def scan_images() -> list[ImageItem]:
    items: list[ImageItem] = []
    for group_dir in sorted(TEST_IMGS_DIR.iterdir()):
        if not group_dir.is_dir():
            continue
        for img_path in sorted(group_dir.iterdir()):
            if img_path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            name_lower = img_path.name.lower()
            if "normal" in name_lower:
                gt = "normal"
            elif "error" in name_lower:
                gt = "error"
            else:
                print(f"⚠ 跳过无法识别的图片: {img_path.name}")
                continue
            items.append(
                ImageItem(path=img_path, group=group_dir.name, ground_truth=gt)
            )
    return items


# ============================================================
# 图片编码
# ============================================================
def build_image_data_url(image_path: Path) -> str:
    suffix = image_path.suffix.lstrip(".").lower()
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:image/{mime};base64,{encoded}"


# ============================================================
# 响应解析：从模型返回文本中提取"正常"或"异常"
# ============================================================
def parse_response(response: str) -> str:
    if not response:
        return "unknown"

    match = re.search(r"【结论】\s*(异常|正常)", response)
    if match:
        return match.group(1)

    match = re.search(r"结论[：:]\s*(异常|正常)", response)
    if match:
        return match.group(1)

    has_ab, has_nor = "异常" in response, "正常" in response
    if has_ab and not has_nor:
        return "异常"
    if has_nor and not has_ab:
        return "正常"
    if has_ab and has_nor:
        idx_ab, idx_nor = response.find("异常"), response.find("正常")
        return "异常" if idx_ab < idx_nor else "正常"

    return "unknown"


# ============================================================
# 连通性测试：逐个检查各模型 API 是否能正常访问
# ============================================================
def test_connectivity(models: list[dict]) -> None:
    """对每个模型发送一条简单文本消息，验证 API 是否可联通。"""
    print("\n" + "=" * 60)
    print("连通性测试开始")
    print("=" * 60)

    reachable = []
    unreachable = []

    # for model_cfg in models:
    #     ep = ENDPOINTS[model_cfg["endpoint"]]
    #     client = OpenAI(base_url=ep["base_url"], api_key=ep["api_key"])
    #     model_name = model_cfg["name"]
    #     endpoint_name = model_cfg["endpoint"]
    #
    #     print(f"\n  测试模型: {model_name} (endpoint: {endpoint_name}) ...", end=" ", flush=True)
    #
    #     try:
    #         completion = client.chat.completions.create(
    #             model=model_name,
    #             messages=[{"role": "user", "content": "你好"}],
    #             max_tokens=10,
    #         )
    #         reply = (completion.choices[0].message.content or "").strip()
    #         print(f"✅ 连通成功 (回复: {reply[:30]})")
    #         reachable.append(model_name)
    #     except Exception as e:
    #         print(f"❌ 连通失败: {e}")
    #         unreachable.append((model_name, str(e)))

    print("\n" + "-" * 60)
    print(f"连通成功: {len(reachable)}/{len(models)} 个模型")
    if reachable:
        print(f"  ✅ {', '.join(reachable)}")
    if unreachable:
        print(f"  ❌ {', '.join(m[0] for m in unreachable)}")
        print("\n连通失败的模型将在正式测试中大概率出错，建议检查 API Key / 网络后重试。")
    print("-" * 60)


# ============================================================
# 单次模型调用（含重试）
# ============================================================
def call_model_once(
    client: OpenAI,
    model_name: str,
    image_data_url: str,
    use_thinking_control: bool,
) -> tuple[str, float, str]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": USER_PROMPT},
            ],
        },
    ]
    kwargs: dict = {"model": model_name, "messages": messages}
    if use_thinking_control:
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    for attempt in range(MAX_RETRIES):
        try:
            start = time.perf_counter()
            completion = client.chat.completions.create(**kwargs)
            elapsed = time.perf_counter() - start
            response_text = completion.choices[0].message.content or ""
            return response_text, elapsed, ""
        except Exception as e:
            err_msg = f"Attempt {attempt + 1}/{MAX_RETRIES}: {e}"
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return "", 0.0, err_msg
    return "", 0.0, "unknown error"


# ============================================================
# 单个任务执行逻辑（模型 × 图片 × 第 N 次重复）
# ============================================================
def _run_single_task(
    model_cfg: dict,
    img: ImageItem,
    run_idx: int,
    client: OpenAI,
) -> RunResult:
    """执行单个 (模型, 图片, 重复次数) 的完整调用逻辑，供线程池调用。"""
    model_name = model_cfg["name"]
    image_data_url = build_image_data_url(img.path)

    response_text, latency, error = call_model_once(
        client,
        model_name,
        image_data_url,
        model_cfg["use_thinking_control"],
    )

    if error:
        parsed = "unknown"
    else:
        parsed = parse_response(response_text)

    gt_abnormal = img.ground_truth == "error"
    pred_abnormal = parsed == "异常"
    is_correct = gt_abnormal == pred_abnormal

    result = RunResult(
        model_name=model_name,
        image_group=img.group,
        image_name=img.path.name,
        ground_truth=img.ground_truth,
        run_index=run_idx + 1,
        raw_response=response_text,
        parsed_result=parsed,
        is_correct=is_correct,
        latency=latency,
        timestamp=datetime.now().isoformat(),
        error=error,
    )

    _save_raw_json(result, img)
    return result


# ============================================================
# 执行全部测试（多模型 + 多重复 并行）
# ============================================================
def run_all_tests(
    images: list[ImageItem], models: list[dict]
) -> list[RunResult]:
    results: list[RunResult] = []
    total = len(models) * len(images) * NUM_RUNS

    # 每个模型创建一个 client（OpenAI client 基于 httpx，线程安全，可跨线程共享）
    clients: dict[str, OpenAI] = {}
    for model_cfg in models:
        ep = ENDPOINTS[model_cfg["endpoint"]]
        clients[model_cfg["name"]] = OpenAI(
            base_url=ep["base_url"], api_key=ep["api_key"]
        )

    # 构建所有任务：模型 × 图片 × 重复次数，全部并行
    tasks = []
    for model_cfg in models:
        for img in images:
            for run_idx in range(NUM_RUNS):
                tasks.append((model_cfg, img, run_idx))

    # 并行线程数 = min(总任务数, 模型数 × 重复次数)
    max_workers = min(len(tasks), len(models) * NUM_RUNS) if tasks else 1

    print(f"\n{'=' * 60}")
    print(f"并行执行 {total} 个任务（{max_workers} 个并行线程）")
    print(f"  · {len(models)} 个模型同时调用")
    print(f"  · 每张图片重复 {NUM_RUNS} 次同时调用")
    print(f"{'=' * 60}\n")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(
                _run_single_task,
                model_cfg,
                img,
                run_idx,
                clients[model_cfg["name"]],
            ): (model_cfg, img, run_idx)
            for model_cfg, img, run_idx in tasks
        }

        done = 0
        for future in as_completed(future_to_task):
            done += 1
            model_cfg, img, run_idx = future_to_task[future]
            model_name = model_cfg["name"]
            img_label = f"{img.group}/{img.path.name}"
            try:
                result = future.result()
                results.append(result)
                if result.error:
                    print(
                        f"  [{done}/{total}] {model_name} | {img_label} | "
                        f"run {run_idx + 1}/{NUM_RUNS} ❌ {result.error[:80]}"
                    )
                else:
                    print(
                        f"  [{done}/{total}] {model_name} | {img_label} | "
                        f"run {run_idx + 1}/{NUM_RUNS} → {result.parsed_result} "
                        f"({result.latency:.2f}s)"
                    )
            except Exception as e:
                print(
                    f"  [{done}/{total}] {model_name} | {img_label} | "
                    f"run {run_idx + 1}/{NUM_RUNS} ❌ 线程异常: {e}"
                )

    return results


def _save_raw_json(result: RunResult, img: ImageItem) -> None:
    model_json_dir = RAW_JSON_DIR / result.model_name
    model_json_dir.mkdir(parents=True, exist_ok=True)
    json_path = (
        model_json_dir
        / f"{img.group}_{img.path.stem}_run{result.run_index}.json"
    )
    json_path.write_text(
        json.dumps(
            {
                "model": result.model_name,
                "image": f"{img.group}/{img.path.name}",
                "ground_truth": result.ground_truth,
                "run": result.run_index,
                "response": result.raw_response,
                "parsed_result": result.parsed_result,
                "is_correct": result.is_correct,
                "latency": result.latency,
                "timestamp": result.timestamp,
                "error": result.error,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# 指标计算
# ============================================================
def calculate_metrics(results: list[RunResult]) -> pd.DataFrame:
    metrics_list: list[dict] = []

    for model_name in sorted({r.model_name for r in results}):
        mr = [r for r in results if r.model_name == model_name]
        TP = TN = FP = FN = 0
        latencies: list[float] = []
        image_consistencies: list[float] = []

        for img_key in sorted(
            {f"{r.image_group}/{r.image_name}" for r in mr}
        ):
            ir = [
                r
                for r in mr
                if f"{r.image_group}/{r.image_name}" == img_key
            ]
            gt = ir[0].ground_truth
            gt_abnormal = gt == "error"
            predictions: list[str] = []

            for r in ir:
                pred_abnormal = r.parsed_result == "异常"
                predictions.append(r.parsed_result)
                latencies.append(r.latency)

                if pred_abnormal and gt_abnormal:
                    TP += 1
                elif not pred_abnormal and not gt_abnormal:
                    TN += 1
                elif pred_abnormal and not gt_abnormal:
                    FP += 1
                elif not pred_abnormal and gt_abnormal:
                    FN += 1

            pred_counts = Counter(predictions)
            majority = pred_counts.most_common(1)[0][1]
            image_consistencies.append(majority / len(predictions))

        total = TP + TN + FP + FN
        precision = TP / (TP + FP) if (TP + FP) else 0
        recall = TP / (TP + FN) if (TP + FN) else 0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0
        )

        metrics_list.append(
            {
                "模型": model_name,
                "总调用次数": total,
                # "真阳性(异常判断为异常)": TP,
                # "真阴性(正常判断为正常)": TN,
                # "假阳性(误报)": FP,
                # "假阴性(漏报)": FN,
                "准确率": round((TP + TN) / total, 4) if total else 0,
                "精确率": round(precision, 4),
                "召回率": round(recall, 4),
                "F1值": round(f1, 4),
                "平均延迟(秒)": round(
                    sum(latencies) / len(latencies), 2
                )
                if latencies
                else 0,
                "最小延迟(秒)": round(min(latencies), 2)
                if latencies
                else 0,
                "最大延迟(秒)": round(max(latencies), 2)
                if latencies
                else 0,
                "稳定性": round(
                    sum(image_consistencies) / len(image_consistencies), 4
                )
                if image_consistencies
                else 0,
            }
        )

    return pd.DataFrame(metrics_list)


# ============================================================
# 模型排名
# ============================================================
def calculate_ranking(metrics_df: pd.DataFrame) -> pd.DataFrame:
    df = metrics_df.copy()
    max_lat = df["平均延迟(秒)"].max()
    if max_lat > 0:
        df["速度得分"] = 1 - (df["平均延迟(秒)"] / max_lat)
    else:
        df["速度得分"] = 1.0

    df["综合得分"] = (
        0.4 * df["准确率"]
        + 0.3 * df["F1值"]
        + 0.2 * df["稳定性"]
        + 0.1 * df["速度得分"]
    )
    df["综合得分"] = df["综合得分"].round(4)
    df = df.sort_values("综合得分", ascending=False).reset_index(drop=True)
    df.insert(0, "排名", range(1, len(df) + 1))
    return df


# ============================================================
# 导出 CSV / Excel
# ============================================================
def export_results(
    results: list[RunResult],
    metrics_df: pd.DataFrame,
    ranking_df: pd.DataFrame,
) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results_df = pd.DataFrame(
        [
            {
                "model": r.model_name,
                "image_group": r.image_group,
                "image_name": r.image_name,
                "ground_truth": r.ground_truth,
                "run": r.run_index,
                "parsed_result": r.parsed_result,
                "is_correct": r.is_correct,
                "latency_s": r.latency,
                "timestamp": r.timestamp,
                "error": r.error,
                "raw_response": r.raw_response,
            }
            for r in results
        ]
    )

    results_df.to_csv(
        RESULTS_DIR / "all_results.csv", index=False, encoding="utf-8-sig"
    )
    metrics_df.to_csv(
        RESULTS_DIR / "metrics_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    ranking_df.to_csv(
        RESULTS_DIR / "model_ranking.csv",
        index=False,
        encoding="utf-8-sig",
    )
    print(f"✅ CSV 已保存到: {RESULTS_DIR}")

    try:
        with pd.ExcelWriter(
            RESULTS_DIR / "metrics_summary.xlsx", engine="openpyxl"
        ) as writer:
            metrics_df.to_excel(writer, sheet_name="metrics", index=False)
            ranking_df.to_excel(writer, sheet_name="ranking", index=False)
            results_df.to_excel(
                writer, sheet_name="all_results", index=False
            )
        print(f"✅ Excel 已保存到: {RESULTS_DIR / 'metrics_summary.xlsx'}")
    except ImportError:
        print("⚠ openpyxl 未安装，仅生成 CSV。安装命令: pip install openpyxl")


# ============================================================
# 主入口
# ============================================================
def main() -> None:
    print("=" * 60)
    print("多模态大模型视觉识别能力评测")
    print("=" * 60)

    # ---- 第一步：连通性测试 ----
    test_connectivity(MODELS)

    images = scan_images()
    print(f"\n扫描到 {len(images)} 张测试图片:")
    for img in images:
        print(f"  {img.group}/{img.path.name} → {img.ground_truth}")

    print(f"\n测试模型 ({len(MODELS)} 个):")
    for m in MODELS:
        print(f"  {m['name']} (endpoint: {m['endpoint']})")

    print(f"\n每张图片重复 {NUM_RUNS} 次")
    total_calls = len(MODELS) * len(images) * NUM_RUNS
    print(f"总调用次数: {total_calls}")

    # try:
    #     input("\n按 Enter 开始测试 (Ctrl+C 取消)...")
    # except (EOFError, KeyboardInterrupt):
    #     print("\n已取消。")
    #     return

    results = run_all_tests(images, MODELS)

    print("\n" + "=" * 60)
    print("计算指标...\n")
    metrics_df = calculate_metrics(results)
    print(metrics_df.to_string(index=False))

    print("\n" + "=" * 60)
    print("模型排名:\n")
    ranking_df = calculate_ranking(metrics_df)
    print(ranking_df.to_string(index=False))

    export_results(results, metrics_df, ranking_df)

    print(f"\n{'=' * 60}")
    print(f"✅ 评测完成！结果保存在: {RESULTS_DIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
