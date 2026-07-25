"""回复决策器 - 判断是否需要回复消息

策略:
    1. 被@时 → 100% 回复
    2. 消息包含触发关键词 → 100% 回复
    3. 普通消息 → 按概率随机回复
"""

import re
import random
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class Planner:
    """回复决策器"""

    def __init__(
        self,
        bot_name: str = "管家",
        reply_probability: float = 0.15,
        keywords: Optional[List[str]] = None,
    ):
        """
        初始化决策器

        Args:
            bot_name: 机器人名称
            reply_probability: 普通消息回复概率 (0-1)
            keywords: 触发关键词列表
        """
        self.bot_name = bot_name
        self.reply_probability = reply_probability
        self.keywords = keywords or []

    def should_reply(
        self,
        content: str,
        is_at_bot: bool = False,
        sender: str = "",
    ) -> bool:
        """
        判断是否需要回复

        Args:
            content: 消息内容
            is_at_bot: 是否@了机器人
            sender: 发送者名称

        Returns:
            是否需要回复
        """
        # 跳过空消息
        if not content or not content.strip():
            return False

        # 策略1: 被@必回
        if is_at_bot:
            logger.debug(f"被@，回复: sender={sender}")
            return True

        # 策略2: 关键词触发
        content_lower = content.lower()
        for keyword in self.keywords:
            if keyword.lower() in content_lower:
                logger.debug(f"关键词命中 '{keyword}'，回复: sender={sender}")
                return True

        # 策略3: 随机概率
        if random.random() < self.reply_probability:
            logger.debug(f"随机回复触发: sender={sender}")
            return True

        return False

    def clean_at_mention(self, content: str) -> str:
        """
        清除消息中的 @ 提及

        例如 "@管家 你好" → "你好"

        Args:
            content: 原始消息内容

        Returns:
            清理后的消息内容
        """
        # 移除 @所有人、@all 等
        content = re.sub(r"@\s*所有[人]\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"@\s*all\s*", "", content, flags=re.IGNORECASE)

        # 移除 @机器人名称
        content = re.sub(
            rf"@\s*{re.escape(self.bot_name)}\s*", "", content, flags=re.IGNORECASE
        )

        # 移除通用的 @xxx 模式（微信群里@某人的格式）
        content = re.sub(r"@[\w\u4e00-\u9fa5]+\s*", "", content)

        return content.strip()

    def check_at_bot(self, content: str, bot_name: str = None) -> bool:
        """
        检查消息是否@了机器人

        Args:
            content: 消息内容
            bot_name: 机器人名称，默认使用 self.bot_name

        Returns:
            是否@了机器人
        """
        name = bot_name or self.bot_name
        return f"@{name}" in content or f"@ {name}" in content
