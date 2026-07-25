"""微信 AI 群聊机器人 - 主入口

功能:
    1. 微信群定时发早安/晚安消息
    2. 根据人设身份在群里聊天（调用大模型回复）
    3. 定时发送生日提醒
    4. 根据策略自动回复群消息

使用方式:
    1. 确保微信 PC 客户端已运行并登录
    2. 在 basic_config/settings.yaml 配置大模型 API
    3. 在 basic_config/persona.yaml 配置人设和群名
    4. 运行: python main.py
"""

import sys
import time
import logging
import threading
from logging.handlers import RotatingFileHandler

from llm.client import LLMClient
from agent.persona import Persona
from agent.memory import MemoryManager
from agent.planner import Planner
from utils.set_logger import get_logger
from wechat.bot import WeChatBot, WeChatMessage
from tools.scheduler import TaskScheduler
from tools.birthday import BirthdayManager

logger = get_logger()


class AutoResponderRobot:
    """微信 AI 群聊机器人主类"""

    def __init__(self):
        """初始化所有组件"""
        logger.info("=" * 50)
        logger.info("微信 AI 群聊机器人启动中...")
        logger.info("=" * 50)

        # 初始化各组件
        self.persona = Persona()
        self.llm = LLMClient()
        self.memory = MemoryManager()
        self.planner = Planner(
            bot_name=self.persona.name,
            reply_probability=self.persona.reply_probability,
            keywords=self.persona.keywords,
        )
        self.birthday_mgr = BirthdayManager()
        self.wx_bot = WeChatBot(listen_groups=self.persona.groups)
        self.scheduler = TaskScheduler()

        logger.info(f"人设: name={self.persona.name}, identity={self.persona.identity}")
        logger.info(f"监听群: {self.persona.groups if self.persona.groups else '所有群'}")
        logger.info(f"回复概率: {self.persona.reply_probability}")
        logger.info(f"触发关键词: {self.persona.keywords}")

    def setup_wechat(self) -> bool:
        """初始化微信连接"""
        if not self.wx_bot.init_wechat():
            logger.error("微信初始化失败！请确保微信 PC 客户端正在运行且已登录。")
            return False
        logger.info("微信连接成功！")
        return True

    def setup_scheduler(self):
        """配置定时任务"""
        # 早安消息
        self.scheduler.add_daily_task(
            self.send_morning_message,
            self.persona.morning_time,
            task_id="morning_greeting",
        )

        # 晚安消息
        self.scheduler.add_daily_task(
            self.send_evening_message,
            self.persona.evening_time,
            task_id="evening_greeting",
        )

        # 生日提醒
        self.scheduler.add_daily_task(
            self.check_birthdays,
            self.persona.birthday_check_time,
            task_id="birthday_check",
        )

        self.scheduler.start()
        logger.info(
            f"定时任务已配置: 早安={self.persona.morning_time}, "
            f"晚安={self.persona.evening_time}, "
            f"生日检查={self.persona.birthday_check_time}"
        )

    def send_morning_message(self):
        """生成并发送早安消息"""
        logger.info("开始发送早安消息...")
        groups = self._get_target_groups()

        for group in groups:
            try:
                msg = self.llm.chat(
                    [
                        {
                            "role": "system",
                            "content": self.persona.build_system_prompt(),
                        },
                        {
                            "role": "user",
                            "content": (
                                "请生成一句早安群消息。"
                                "要求：阳光积极、幽默自然、适合微信群、一句话就好、不要太长。"
                            ),
                        },
                    ],
                    temperature=0.9,
                    max_tokens=100,
                )
                if msg:
                    self.wx_bot.send_group_message(group, msg)
                    logger.info(f"早安消息已发送到群 '{group}': {msg}")
                    time.sleep(3)  # 避免发送太快
            except Exception as e:
                logger.error(f"发送早安消息到群 '{group}' 失败: {e}")

    def send_evening_message(self):
        """生成并发送晚安消息"""
        logger.info("开始发送晚安消息...")
        groups = self._get_target_groups()

        for group in groups:
            try:
                msg = self.llm.chat(
                    [
                        {
                            "role": "system",
                            "content": self.persona.build_system_prompt(),
                        },
                        {
                            "role": "user",
                            "content": (
                                "请生成一句晚安群消息。"
                                "要求：温馨自然、不要太长、适合微信群、一句话就好。"
                            ),
                        },
                    ],
                    temperature=0.9,
                    max_tokens=100,
                )
                if msg:
                    self.wx_bot.send_group_message(group, msg)
                    logger.info(f"晚安消息已发送到群 '{group}': {msg}")
                    time.sleep(3)
            except Exception as e:
                logger.error(f"发送晚安消息到群 '{group}' 失败: {e}")

    def check_birthdays(self):
        """检查并发送生日提醒"""
        logger.info("开始检查今日生日...")
        birthdays = self.birthday_mgr.get_today_birthdays()

        if not birthdays:
            logger.info("今天没有人过生日")
            return

        for name, birthday, group in birthdays:
            try:
                prompt = self.birthday_mgr.build_birthday_prompt(name)
                msg = self.llm.chat_with_system(
                    system_prompt=self.persona.build_system_prompt(),
                    user_message=prompt,
                    temperature=0.9,
                    max_tokens=100,
                )
                if msg and group:
                    self.wx_bot.send_group_message(group, msg)
                    logger.info(f"生日提醒已发送: name={name}, group={group}")
                    time.sleep(3)
                elif msg and not group:
                    # 如果没有配置群名，发送到所有目标群
                    for g in self._get_target_groups():
                        self.wx_bot.send_group_message(g, msg)
                        time.sleep(3)
            except Exception as e:
                logger.error(f"发送生日提醒失败: name={name}, error={e}")

    def process_message(self, msg: WeChatMessage):
        """
        处理单条微信消息

        Args:
            msg: 微信消息对象
        """
        sender = msg.sender
        content = msg.content
        group = msg.chat

        # 跳过自己的消息
        if sender == self.persona.name:
            return

        # 跳过非目标群的消息
        if group and not self.persona.should_listen_group(group):
            return

        # 检查是否@了机器人
        is_at = self.planner.check_at_bot(content, self.persona.name)

        # 判断是否需要回复
        if not self.planner.should_reply(content, is_at, sender):
            return

        logger.info(f"回复触发: sender={sender}, group={group}, content={content[:50]}")

        # 存储消息到记忆
        self.memory.add_message(sender, group, content, "user", user_id=sender)

        # 获取对话历史
        history = self.memory.get_recent_history(group, limit=10)

        # 构建发送给 LLM 的消息列表
        system_prompt = self.persona.build_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]

        # 添加记忆上下文
        memory_context = self.memory.build_memory_context(sender)
        if memory_context:
            messages.append({"role": "system", "content": memory_context})

        # 添加历史对话
        messages.extend(history)

        # 清理 @ 提及后添加当前消息
        clean_content = self.planner.clean_at_mention(content)
        messages.append({"role": "user", "content": f"{sender}: {clean_content}"})

        # 调用大模型获取回复
        reply = self.llm.chat(
            messages,
            temperature=self.persona.temperature,
            max_tokens=self.persona.max_tokens,
        )

        if reply:
            # 存储回复到记忆
            self.memory.add_message(self.persona.name, group, reply, "assistant")

            # 发送回复
            self.wx_bot.send_group_message(group, reply)
            logger.info(f"已回复: group={group}, reply={reply[:80]}")

            # 异步提取记忆（不阻塞主流程）
            try:
                memory_content = self.llm.extract_memory(content)
                if memory_content:
                    self.memory.add_memory(sender, memory_content)
            except Exception as e:
                logger.debug(f"记忆提取失败（非致命）: {e}")
        else:
            logger.warning(f"LLM 返回空回复: sender={sender}, content={content[:50]}")

    def run(self):
        """主运行循环"""
        logger.info("正在初始化...")

        # 初始化微信
        if not self.setup_wechat():
            logger.error("微信初始化失败，程序退出。")
            logger.error("请确保:")
            logger.error("  1. Windows 微信 PC 客户端正在运行")
            logger.error("  2. 微信已登录")
            logger.error("  3. 已安装 wxauto4: pip install wxauto4")
            return

        # 配置定时任务
        self.setup_scheduler()

        logger.info("=" * 50)
        logger.info("机器人已启动！正在监听微信消息...")
        logger.info("按 Ctrl+C 停止运行")
        logger.info("=" * 50)

        # 主循环
        try:
            while True:
                msgs = self.wx_bot.get_messages()
                for msg in msgs:
                    try:
                        self.process_message(msg)
                    except Exception as e:
                        logger.error(f"处理消息失败: {e}", exc_info=True)
                time.sleep(3)  # 每 3 秒轮询一次
        except KeyboardInterrupt:
            logger.info("收到停止信号，正在关闭...")
        except Exception as e:
            logger.error(f"运行异常: {e}", exc_info=True)
        finally:
            self.scheduler.shutdown()
            logger.info("机器人已停止。")

    def _get_target_groups(self) -> list:
        """
        获取目标群列表

        如果配置了 groups，使用配置的群；
        否则尝试获取微信当前所有聊天窗口。

        Returns:
            群名列表
        """
        if self.persona.groups:
            return list(self.persona.groups)

        # 尝试获取所有聊天
        chats = self.wx_bot.get_all_chats()
        if chats:
            logger.info(f"未配置群名，将发送到所有聊天窗口: {chats}")
            return chats

        logger.warning("未找到任何聊天窗口，请在 persona.yaml 中配置 groups")
        return []


if __name__ == "__main__":
    robot = AutoResponderRobot()
    robot.run()
