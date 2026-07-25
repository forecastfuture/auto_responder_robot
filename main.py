"""微信 AI 自动回复机器人 - 极简版

功能:
    1. 监听微信新消息
    2. 调用大模型生成回复
    3. 将回复发送回对应聊天窗口

使用方式:
    1. 确保微信 PC 客户端已运行并登录
    2. 在 basic_config/settings.yaml 配置大模型 API 和 system_prompt
    3. 运行: python main.py
"""

import time
import logging

from llm.client import LLMClient
from wechat.bot import WeChatBot
from utils.set_logger import get_logger
from config import settings

logger = get_logger()

# 轮询间隔（秒），pyweixin UI 自动化操作较慢，不宜过短
POLL_INTERVAL = settings.POLL_INTERVAL


def main():
    """主函数：初始化微信 + 大模型，轮询消息并自动回复"""

    # --- 初始化微信 ---
    wx_bot = WeChatBot()
    if not wx_bot.init_wechat():
        logger.error("微信初始化失败！请确保微信 PC 客户端正在运行且已登录。")
        logger.error("  1. Windows 微信 PC 客户端正在运行")
        logger.error("  2. 微信已登录")
        logger.error("  3. 已安装 pywechat: pip install pywechat127 --user --no-cache-dir")
        return

    # --- 初始化大模型 ---
    llm = LLMClient()
    system_prompt = str(settings.get("system_prompt", "你是一个友好的聊天助手。"))
    logger.info(f"系统提示词: {system_prompt[:80]}...")

    logger.info("=" * 50)
    logger.info("机器人已启动！正在监听微信消息...")
    logger.info("按 Ctrl+C 停止运行")
    logger.info("=" * 50)

    # --- 主循环：轮询消息 → 调用大模型 → 回复 ---
    try:
        while True:
            messages = wx_bot.get_messages()
            for msg in messages:
                try:
                    logger.info(f"收到消息: {msg}")

                    # 调用大模型生成回复
                    reply = llm.chat_with_system(
                        system_prompt=system_prompt,
                        user_message=f"{msg.sender}: {msg.content}",
                    )

                    if reply:
                        wx_bot.send_message(msg.chat, reply)
                        logger.info(f"已回复 [{msg.chat}]: {reply[:80]}")
                    else:
                        logger.warning(f"大模型返回空回复: {msg}")

                except Exception as e:
                    logger.error(f"处理消息失败: {e}", exc_info=True)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭...")
    except Exception as e:
        logger.error(f"运行异常: {e}", exc_info=True)
    finally:
        logger.info("机器人已停止。")


if __name__ == "__main__":
    main()
