"""人设管理 - 从 persona.yaml 加载人设配置，构建系统提示词"""

import logging
from typing import List, Optional

from config import settings, persona_settings

logger = logging.getLogger(__name__)


class Persona:
    """机器人人设管理"""

    def __init__(self):
        # 基础信息
        self.name: str = str(persona_settings.get("name", "管家"))
        self.age: int = int(persona_settings.get("age", 28))
        self.identity: str = str(persona_settings.get("identity", "私人管家"))

        # 风格与规则
        self.style: List[str] = list(persona_settings.get("style") or [])
        self.knowledge: List[str] = list(persona_settings.get("knowledge") or [])
        self.rules: List[str] = list(persona_settings.get("rules") or [])

        # 群聊配置
        self.groups: List[str] = list(persona_settings.get("groups") or [])

        # 回复策略
        self.reply_probability: float = float(
            persona_settings.get("reply_probability") or 0.15
        )
        self.keywords: List[str] = list(persona_settings.get("keywords") or [])

        # 定时任务时间
        self.morning_time: str = str(persona_settings.get("morning_time", "08:00"))
        self.evening_time: str = str(persona_settings.get("evening_time", "22:30"))
        self.birthday_check_time: str = str(
            persona_settings.get("birthday_check_time", "09:00")
        )

        # LLM 参数
        llm_params = persona_settings.get("llm_params") or {}
        self.temperature: float = float(llm_params.get("temperature") or 0.8)
        self.max_tokens: int = int(llm_params.get("max_tokens") or 1000)

        # 从 settings.yaml 获取系统提示词
        self.system_prompt: str = str(settings.get("system_prompt", ""))

        logger.info(f"人设加载完成: name={self.name}, identity={self.identity}")

    def build_system_prompt(self) -> str:
        """
        构建完整的系统提示词

        合并 settings.yaml 中的 system_prompt 和 persona.yaml 中的人设信息

        Returns:
            完整的系统提示词
        """
        parts = []

        # 基础系统提示词（来自 settings.yaml）
        if self.system_prompt:
            parts.append(self.system_prompt)

        # 人设信息
        parts.append(f"你的名字是{self.name}。")
        parts.append(f"你的身份: {self.identity}。")
        parts.append(f"你的年龄: {self.age}岁。")

        # 聊天风格
        if self.style:
            parts.append(f"聊天风格: {'、'.join(self.style)}。")

        # 知识领域
        if self.knowledge:
            parts.append(f"知识领域: {'、'.join(self.knowledge)}。")

        # 规则
        if self.rules:
            parts.append(f"规则: {'、'.join(self.rules)}。")

        return "\n".join(parts)

    def should_listen_group(self, group_name: str) -> bool:
        """
        判断是否需要监听某个群

        Args:
            group_name: 群名

        Returns:
            如果配置了 groups 列表且为空，则监听所有群；
            否则只监听配置列表中的群
        """
        if not self.groups:
            return True
        return group_name in self.groups
