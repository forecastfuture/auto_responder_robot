"""人设管理 - 从 persona.yaml 加载人设配置，构建系统提示词

同时管理长期记忆的读写：长期记忆保存在 persona.yaml 的 "长期记忆" 键下。
对话完成后实时更新该文件。
"""

import logging
import os
from typing import List, Optional

import yaml

from config import settings, persona_settings

logger = logging.getLogger(__name__)

PERSONA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "basic_config", "persona.yaml")


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

    # ==================== 长期记忆（persona.yaml） ====================

    @staticmethod
    def get_long_term_memories() -> List[str]:
        """读取 persona.yaml 中的长期记忆列表"""
        try:
            with open(PERSONA_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            memories = data.get("长期记忆", [])
            if isinstance(memories, list):
                return [str(m) for m in memories if str(m).strip()]
            if isinstance(memories, str):
                return [memories.strip()] if memories.strip() else []
            return []
        except Exception as e:
            logger.error(f"读取长期记忆失败: {e}")
            return []

    @staticmethod
    def add_long_term_memory(content: str) -> bool:
        """
        向 persona.yaml 添加一条长期记忆

        实时写入文件，对话完成后即可持久化。

        Args:
            content: 记忆内容

        Returns:
            是否添加成功
        """
        content = content.strip()
        if not content:
            return False
        try:
            with open(PERSONA_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            memories = data.get("长期记忆", [])
            if not isinstance(memories, list):
                memories = [memories] if memories else []
            # 去重：已存在则不重复添加
            if content in memories:
                logger.info(f"长期记忆已存在，跳过: {content[:50]}")
                return True
            memories.append(content)
            data["长期记忆"] = memories
            with open(PERSONA_FILE, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            logger.info(f"长期记忆已保存到 persona.yaml: {content[:50]}")
            return True
        except Exception as e:
            logger.error(f"保存长期记忆失败: {e}")
            return False

    def build_long_term_memory_text(self) -> str:
        """构建长期记忆提示文本"""
        memories = self.get_long_term_memories()
        if not memories:
            return ""
        return "## 长期记忆（生活习惯、爱好、重要信息）\n" + "\n".join(f"- {m}" for m in memories)

    # ==================== 系统提示词构建 ====================

    def build_system_prompt(self) -> str:
        """
        构建完整的系统提示词

        合并 settings.yaml 中的 system_prompt 和 persona.yaml 中的人设信息及长期记忆

        Returns:
            完整的系统提示词
        """
        parts = []

        # 基础系统提示词（来自 settings.yaml）
        if self.system_prompt:
            parts.append(self.system_prompt)

        # 长期记忆（来自 persona.yaml）
        memory_text = self.build_long_term_memory_text()
        if memory_text:
            parts.append(memory_text)

        return "\n\n".join(parts)

    def should_listen_group(self, group_name: str) -> bool:
        """判断是否需要监听某个群"""
        if not self.groups:
            return True
        return group_name in self.groups
