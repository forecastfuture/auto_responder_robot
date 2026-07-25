"""LLM 模型可用性测试"""

import time

from llm.client import LLMClient
from utils.set_logger import get_logger

logger = get_logger()


def test_model_sync():
    """同步测试模型可用性"""
    start_time = time.time()

    # 使用项目统一的 LLM 客户端
    client = LLMClient()

    messages = [
        {"role": "system", "content": "你是一个有用的AI助手，请用简短的话回答问题。"},
        {"role": "user", "content": "你好！请简单介绍一下你自己, 你是谁, 你有多大, 多少B, 有什么功能, 是否有多模态。哪一个版本啊, 不要废话, 说具体一点"},
    ]

    reply = client.chat(messages, temperature=0.7, max_tokens=1024)

    elapsed = time.time() - start_time
    print(f"✅ 模型调用成功！耗时: {elapsed:.2f}秒")
    print(f"回复内容: {reply}")

    # pytest 断言：返回非空即视为可用
    assert reply, "模型返回空回复，调用失败"


if __name__ == "__main__":
    logger.info("开始同步测试模型可用性...")
    test_model_sync()
