"""图片消息回复测试 - 验证 图片检测→保存→多模态LLM→回复 全链路

运行前确保:
    1. 微信 PC 客户端已运行并登录
    2. pip install pywechat127 --user --no-cache-dir
    3. "测试群" 中有人最近发过一张图片（非自己发的）

用法: python -m tests.test_image_reply
"""

import os
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
        print("微信初始化失败")
        return

    # 2. 拉取测试群最近消息（含图片保存）
    print("=" * 50)
    print("拉取测试群最近5条消息...")
    msgs = bot.get_recent_messages(TEST_GROUP, count=5)
    if not msgs:
        print(f"'{TEST_GROUP}' 中没有找到消息")
        return

    print(f"共拉取到 {len(msgs)} 条消息:")
    for m in msgs:
        kind = "图片" if m.is_image else "文本"
        img_info = f" -> 图片路径: {m.image_path}" if m.is_image else ""
        print(f"  [{kind}] {m.sender}: {m.content[:50]}{img_info}")

    # 3. 查找最后一条他人发送的图片消息
    target_msg = None
    for m in reversed(msgs):
        if bot._is_self_message(m.sender, m.content):
            continue
        if m.is_image:
            target_msg = m
            break

    if not target_msg:
        print("没有找到他人发送的图片消息")
        print("请在测试群中发送一张图片后重新运行此测试")
        return

    print(f"\n找到图片消息: [{target_msg.sender}] {target_msg.content}")
    print(f"图片路径: {target_msg.image_path}")

    if not target_msg.image_path or not os.path.exists(target_msg.image_path):
        print("图片文件不存在，无法进行多模态识别")
        print("回退到纯文本处理...")
        # 4a. 纯文本回退
        llm = LLMClient()
        system_prompt = str(settings.get("system_prompt", "你是一个友好的聊天助手。"))
        user_msg = f"{target_msg.sender} 发送了一张图片，但无法获取图片内容"
        reply = llm.chat_with_system(
            system_prompt=system_prompt,
            user_message=user_msg,
        )
    else:
        # 4b. 多模态调用
        print(f"\n使用多模态 LLM 识别图片...")
        llm = LLMClient()
        system_prompt = str(settings.get("system_prompt", "你是一个友好的聊天助手。"))
        user_text = f"{target_msg.sender} 发送了图片，请识别图片内容并自然回复"
        reply = llm.chat_multimodal(
            system_prompt=system_prompt,
            user_text=user_text,
            image_paths=[target_msg.image_path],
        )

    if not reply:
        print("大模型返回空回复")
        return

    print(f"\n生成回复: {reply}")

    # 5. 发送回复到测试群
    if bot.send_message(TEST_GROUP, reply):
        print(f"回复已发送到 '{TEST_GROUP}'")
    else:
        print("发送失败")


if __name__ == "__main__":
    main()
