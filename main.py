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
from utils.set_logger import get_logger
from config import settings

logger = get_logger()

POLL_INTERVAL = settings.POLL_INTERVAL


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

    logger.info("=" * 50)
    logger.info("机器人已启动！正在监听微信消息...")
    logger.info(f"监听会话: {reply_chats}")
    logger.info(f"当前模型: {llm.model_name}（多模态: 支持图片识别）")
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

                    # 保存用户消息到记忆数据库
                    memory_mgr.add_message(msg.sender, target_chat, msg.content, "user")

                    # 功能1: 实时时间
                    time_prompt = build_time_prompt()

                    # 功能2: 拉取最近5条消息作为上下文
                    recent_msgs = wx_bot.get_recent_messages(target_chat, count=5)
                    context_prompt = build_context_prompt(recent_msgs, msg)

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

                    # 调用大模型生成回复（功能0: 完整提示词已在 LLMClient 内写入日志）
                    if image_paths:
                        reply = llm.chat_multimodal(
                            system_prompt=full_system_prompt,
                            user_text=f"{msg.sender}: {msg.content}",
                            image_paths=image_paths,
                            history=None,
                            temperature=persona.temperature,
                            max_tokens=persona.max_tokens,
                        )
                    else:
                        reply = llm.chat_with_system(
                            system_prompt=full_system_prompt,
                            user_message=f"{msg.sender}: {msg.content}",
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
        logger.info("机器人已停止。")


if __name__ == "__main__":
    main()
