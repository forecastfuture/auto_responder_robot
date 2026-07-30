"""微信 AI 自动回复机器人

功能:
    1. 监听微信新消息
    2. 检测到新消息时，拉取该会话最近5条消息作为上下文
    3. 在提示词中加入实时时间（年月日时分秒）
    4. 在提示词中加入长期记忆（来自 persona.yaml）
    5. 调用多模态大模型生成回复（支持图片识别）
    6. 完整提示词写入日志
    7. 对话完成后提取长期记忆并实时保存到 persona.yaml

使用方式:
    1. 确保微信 PC 客户端已运行并登录
    2. 在 basic_config/settings.yaml 配置大模型 API 和 system_prompt
    3. 在 basic_config/persona.yaml 配置长期记忆
    4. 运行: python main.py
"""

import time
import random
from datetime import datetime

from llm.client import LLMClient
from wechat.bot import WeChatBot
from agent.persona import Persona
from agent.memory import MemoryManager
from tools.scheduler import TaskScheduler
from utils.set_logger import get_logger
from config import settings

logger = get_logger()

POLL_INTERVAL = settings.POLL_INTERVAL

# 回复触发关键词（除 @角色名 外）
ROLE = str(settings.get("ROLE") or "twenty")
ROLE_MENTION_KEYWORDS = [
    str(k).strip()
    for k in (settings.get("ROLE_MENTION_KEYWORDS") or [])
    if str(k).strip()
]


def build_time_prompt() -> str:
    """构建实时时间提示词（功能1）"""
    now = datetime.now()
    # 手动拼接中文字符，避免 strftime 在 Windows 上无法处理中文
    time_str = f"{now.year}年{now.month:02d}月{now.day:02d}日 {now.hour:02d}:{now.minute:02d}:{now.second:02d}"
    return f"## 当前时间\n{time_str}（{_weekday_cn(now)}）"


def _weekday_cn(dt: datetime) -> str:
    names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return names[dt.weekday()]


def build_context_prompt(recent_msgs, current_msg) -> str:
    """
    构建对话上下文提示词（功能2+3）

    将最近5条消息和当前消息整理为上下文文本。
    """
    lines = ["## 最近对话上下文"]
    has_content = False
    for m in recent_msgs:
        is_current = (m.sender == current_msg.sender and m.content == current_msg.content)
        tag = "（当前消息）" if is_current else ""
        kind = "[图片]" if m.is_image else ""
        lines.append(f"- {m.sender}{tag}: {m.content} {kind}".rstrip())
        has_content = True
    return "\n".join(lines) if has_content else ""


def build_memory_prompt(memory_mgr: MemoryManager, chat_name: str) -> str:
    """构建历史对话记忆提示词（功能3 - 需要记忆）"""
    history = memory_mgr.get_recent_history(chat_name, limit=10)
    if not history:
        return ""
    lines = ["## 历史对话记忆"]
    for h in history:
        lines.append(f"- [{h['role']}] {h['content']}")
    return "\n".join(lines)


def build_cron_system_prompt(persona: Persona, chat_name: str, raw_message: str) -> str:
    """构建定时任务的 LLM 系统提示词

    根据原始消息内容智能识别场景（早安/午安/晚安等），
    指导 LLM 生成自然、不重复的问候语，而非僵硬照搬原文。
    """
    base_prompt = persona.build_system_prompt()
    time_prompt = build_time_prompt()

    instruction = (
        f"## 定时消息生成指令\n"
        f"这是一条定时触发的消息，目标会话是「{chat_name}」。\n"
        f"原始定时消息意图：{raw_message}\n\n"
        f"请根据这个意图，用你自己的风格自然地表达，不要僵硬地照搬原文。\n"
        f"每次生成的措辞要有变化，避免千篇一律。\n"
    )

    # 根据消息内容识别场景，附加不同指令
    morning_kw = ["早安", "早上好", "早好", "早呀", "早"]
    noon_kw = ["中午好", "午安"]
    afternoon_kw = ["下午好", "午后好"]
    evening_kw = ["晚上好", "晚安", "晚安好", "晚好"]

    if any(kw in raw_message for kw in morning_kw):
        instruction += (
            "\n### 早安运势占卜\n"
            "这是早安问候。在问候之后，请附带今日运势占卜，格式参考：\n"
            "- 今日运势（用星级表示，如 ★★★☆☆）\n"
            "- 幸运色\n"
            "- 宜（1~2件适合做的事）\n"
            "- 忌（1~2件不宜做的事）\n"
            "- 一句简短运势提醒\n"
            "运势内容每次随机生成，轻松有趣，像一只高冷小猫给主人的每日运势播报。\n"
            "整体控制在5行以内。\n"
        )
    elif any(kw in raw_message for kw in noon_kw):
        instruction += (
            "\n这是午间问候。可以轻松地提醒午餐或午休，语气自然随意，2~3行即可。\n"
        )
    elif any(kw in raw_message for kw in afternoon_kw):
        instruction += (
            "\n这是下午问候。可以轻松活泼一些，关心下午的状态或提提神，2~3行即可。\n"
        )
    elif any(kw in raw_message for kw in evening_kw):
        instruction += (
            "\n这是晚间问候。可以温暖贴心一些，提醒今天辛苦了或该休息了，2~3行即可。\n"
        )
    else:
        instruction += "\n请根据消息意图自然表达，2~3行即可。\n"

    return "\n\n".join(p for p in [base_prompt, time_prompt, instruction] if p)


def send_cron_message(
    llm: LLMClient,
    persona: Persona,
    wx_bot: WeChatBot,
    chat_name: str,
    raw_message: str,
):
    """定时任务回调：先让 LLM 生成自然回复，再发送到微信

    如果 LLM 调用失败，回退到发送原始消息，确保定时消息不会丢失。
    """
    try:
        system_prompt = build_cron_system_prompt(persona, chat_name, raw_message)
        user_text = (
            f"请根据上述意图生成一条发送给「{chat_name}」的自然消息。"
            "直接输出消息内容，不要任何解释或多余说明。"
        )

        reply = llm.chat_with_system(
            system_prompt=system_prompt,
            user_message=user_text,
            temperature=max(persona.temperature, 0.9),  # 定时消息提高随机性，避免千篇一律
            max_tokens=persona.max_tokens,
        )

        if reply:
            wx_bot.send_message(chat_name, reply)
            logger.info(f"定时任务LLM生成并已发送 [{chat_name}]: {reply[:80]}")
        else:
            logger.warning(f"LLM生成定时消息为空，回退到原始消息: {raw_message}")
            wx_bot.send_message(chat_name, raw_message)
    except Exception as e:
        logger.error(f"定时任务LLM生成失败，回退到原始消息: {e}", exc_info=True)
        try:
            wx_bot.send_message(chat_name, raw_message)
        except Exception:
            logger.error(f"回退发送原始消息也失败: {chat_name}")


def setup_cron_tasks(
    scheduler: TaskScheduler,
    wx_bot: WeChatBot,
    llm: LLMClient,
    persona: Persona,
):
    """从 settings.yaml 加载 CRON_TASKS 配置并注册定时任务

    定时消息不再直接发送硬编码文本，而是先经过 LLM 生成自然、
    随机的问候语（早安附带运势占卜），再发送到目标会话。

    配置格式（settings.yaml 中）:
        CRON_TASKS:
          - '0 8 * * *': ['会话名称', '发送的消息']
          - '30 12 * * *': ['另一个会话', '中午好']
    cron 表达式为 5 段标准格式: 分 时 日 月 周
    """
    cron_tasks = settings.get("CRON_TASKS") or []
    if not cron_tasks:
        logger.info("未配置 CRON_TASKS，跳过定时任务初始化")
        return

    registered = 0
    for i, task_entry in enumerate(cron_tasks):
        try:
            # task_entry 是单键字典: {'0 8 * * *': ['会话名', '消息内容']}
            for cron_expr, params in task_entry.items():
                if not params or len(params) < 2:
                    logger.warning(f"CRON_TASKS 第{i}项参数不足，跳过: {task_entry}")
                    continue
                chat_name = str(params[0]).strip()
                message = str(params[1]).strip()
                if not chat_name or not message:
                    logger.warning(f"CRON_TASKS 第{i}项会话名或消息为空，跳过")
                    continue
                task_id = f"cron_{i}_{cron_expr.replace(' ', '_')}"
                scheduler.add_cron_task(
                    send_cron_message,
                    cron_expr,
                    task_id=task_id,
                    llm=llm,
                    persona=persona,
                    wx_bot=wx_bot,
                    chat_name=chat_name,
                    raw_message=message,
                )
                logger.info(
                    f"注册定时任务(LLM增强): {cron_expr} -> 会话[{chat_name}] 意图[{message[:20]}]"
                )
                registered += 1
        except Exception as e:
            logger.error(f"注册 CRON_TASKS 第{i}项失败: {e}", exc_info=True)

    logger.info(f"共注册 {registered} 个定时任务")


def main():
    """主函数：初始化微信 + 大模型，轮询消息并自动回复"""

    # --- 加载回复白名单 ---
    reply_chats = [str(c).strip() for c in (settings.get("REPLY_CHATS") or []) if str(c).strip()]
    if not reply_chats:
        logger.error("未配置 REPLY_CHATS！请在 basic_config/settings.yaml 中指定要回复的会话名称。")
        return
    logger.info(f"只监听以下会话: {reply_chats}")

    # --- 初始化微信 ---
    wx_bot = WeChatBot(listen_groups=reply_chats)
    if not wx_bot.init_wechat():
        logger.error("微信初始化失败！请确保微信 PC 客户端正在运行且已登录。")
        return

    # --- 初始化大模型 ---
    llm = LLMClient()

    # --- 初始化人设（含长期记忆） ---
    persona = Persona()
    base_system_prompt = persona.build_system_prompt()
    logger.info(f"系统提示词已加载（含长期记忆），长度: {len(base_system_prompt)} 字符")

    # --- 初始化记忆系统 ---
    memory_mgr = MemoryManager()

    # --- 初始化定时任务调度器 ---
    scheduler = TaskScheduler()
    setup_cron_tasks(scheduler, wx_bot, llm, persona)
    scheduler.start()

    logger.info("=" * 50)
    logger.info("机器人已启动！正在监听微信消息...")
    logger.info(f"监听会话: {reply_chats}")
    logger.info(f"文本模型: {llm.model_name} | 多模态模型: {llm.img_model_name}")
    logger.info("按 Ctrl+C 停止运行")
    logger.info("=" * 50)

    # --- 主循环 ---
    try:
        while True:
            for msg in wx_bot.get_messages():
                try:
                    logger.info(f"收到消息: {msg}")

                    target_chat = msg.chat.strip()
                    if target_chat not in reply_chats:
                        logger.warning(f"非目标会话，跳过: [{target_chat}]")
                        continue

                    # 保存用户消息到记忆数据库（无论是否回复都保存）
                    memory_mgr.add_message(msg.sender, target_chat, msg.content, "user")

                    # ===== 回复决策：只有@角色或需要角色回应时才回复 =====
                    # 构建上下文文本用于辅助判断
                    recent_msgs = wx_bot.get_cached_recent_messages(target_chat)
                    context_for_judge = " | ".join(
                        f"{m.sender}:{m.content[:20]}" for m in recent_msgs
                    )

                    need_reply = llm.should_reply(
                        role=ROLE,
                        sender=msg.sender,
                        content=msg.content,
                        mention_keywords=ROLE_MENTION_KEYWORDS,
                        context=context_for_judge,
                    )

                    if not need_reply:
                        logger.info(
                            f"消息不需要回复，仅记录: [{target_chat}] {msg.sender}: {msg.content[:50]}"
                        )
                        continue

                    logger.info(f"消息需要回复，开始生成回复: [{target_chat}] {msg.sender}: {msg.content[:50]}")

                    # 功能1: 实时时间
                    time_prompt = build_time_prompt()

                    # 功能2: 使用已缓存的最近5条消息作为上下文
                    context_prompt = build_context_prompt(recent_msgs, msg)
                    if recent_msgs:
                        logger.info(f"上下文消息({len(recent_msgs)}条): "
                                    + " | ".join(f"{m.sender}:{m.content[:20]}" for m in recent_msgs))

                    # 功能3: 历史对话记忆
                    memory_prompt = build_memory_prompt(memory_mgr, target_chat)

                    # 组合完整系统提示词
                    full_system_prompt = "\n\n".join(
                        p for p in [base_system_prompt, time_prompt, context_prompt, memory_prompt]
                        if p
                    )

                    # 功能4: 多模态 - 收集图片路径
                    image_paths = [m.image_path for m in recent_msgs if m.is_image and m.image_path]
                    # 当前消息如果是图片也加入
                    if msg.is_image and msg.image_path:
                        image_paths.append(msg.image_path)
                    # 去重（同一条消息可能同时在 recent_msgs 和 msg 中）
                    image_paths = list(dict.fromkeys(image_paths))

                    if image_paths:
                        logger.info(f"检测到图片消息，共 {len(image_paths)} 张图片，使用多模态调用")

                    # 调用大模型生成回复（功能0: 完整提示词已在 LLMClient 内写入日志）
                    if image_paths:
                        # 多模态调用：附上图片让 LLM 识别内容
                        user_text = f"{msg.sender} 发送了图片，请识别图片内容并自然回复"
                        reply = llm.chat_multimodal(
                            system_prompt=full_system_prompt,
                            user_text=user_text,
                            image_paths=image_paths,
                            history=None,
                            temperature=persona.temperature,
                            max_tokens=persona.max_tokens,
                        )
                    else:
                        # 纯文本调用
                        user_msg = f"{msg.sender}: {msg.content}"
                        # 如果是图片消息但未能保存图片，告知 LLM
                        if msg.is_image:
                            user_msg = f"{msg.sender} 发送了一张图片，但无法获取图片内容"
                        reply = llm.chat_with_system(
                            system_prompt=full_system_prompt,
                            user_message=user_msg,
                            temperature=persona.temperature,
                            max_tokens=persona.max_tokens,
                        )

                    if reply:
                        wx_bot.send_message(target_chat, reply)
                        logger.info(f"已回复 [{target_chat}]: {reply[:80]}")
                        # 保存回复到记忆数据库
                        memory_mgr.add_message("twenty", target_chat, reply, "assistant")

                        # 功能5: 提取长期记忆并保存到 persona.yaml
                        try:
                            memory_item = llm.extract_memory(msg.content, reply)
                            if memory_item:
                                persona.add_long_term_memory(memory_item)
                                # 重新加载系统提示词以包含新记忆
                                base_system_prompt = persona.build_system_prompt()
                        except Exception as e:
                            logger.warning(f"提取长期记忆失败: {e}")
                    else:
                        logger.warning(f"大模型返回空回复: {msg}")

                except Exception as e:
                    logger.error(f"处理消息失败: {e}", exc_info=True)

            time.sleep(random.uniform(1, 2))
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭...")
    except Exception as e:
        logger.error(f"运行异常: {e}", exc_info=True)
    finally:
        try:
            scheduler.shutdown()
        except Exception:
            pass
        logger.info("机器人已停止。")


if __name__ == "__main__":
    main()
