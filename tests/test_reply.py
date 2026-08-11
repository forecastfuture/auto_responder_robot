"""简化回复测试 - 使用测试群最后一条消息验证 收消息→LLM→回复 链路

运行前确保:
    1. 微信 PC 客户端已运行并登录
    2. pip install pywechat127 --user --no-cache-dir
    3. "测试群" 中有他人发的消息（非自己发的）

用法: python -m tests.test_reply
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat.bot import WeChatBot
from llm.client import LLMClient
from config import settings

TEST_GROUP = "测试群"


def main():
    # 1. 初始化微信
    bot = WeChatBot(listen_groups=[TEST_GROUP])
    if not bot.init_wechat():
        print("❌ 微信初始化失败")
        return

    # 2. 拉取测试群最后一条他人消息，当作最新接收的消息
    msg = bot.get_last_message(TEST_GROUP)
    if not msg:
        print(f"❌ '{TEST_GROUP}' 中没有找到他人的消息")
        return

    print(f"📩 收到消息: [{msg.sender}] {msg.content}")

    # 3. 调用大模型生成回复
    llm = LLMClient()
    system_prompt = str(settings.get("system_prompt", "你是一个友好的聊天助手。"))
    reply = llm.chat_with_system(
        system_prompt=system_prompt,
        user_message=f"{msg.sender}: {msg.content}",
    )

    if not reply:
        print("❌ 大模型返回空回复")
        return

    print(f"🤖 生成回复: {reply}")

    # 4. 发送回复到测试群
    if bot.send_message(TEST_GROUP, reply):
        print(f"✅ 回复已发送到 '{TEST_GROUP}'")
    else:
        print("❌ 发送失败")


if __name__ == "__main__":
    main()
