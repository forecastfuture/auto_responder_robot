"""LLM 网关 - OpenAI 兼容客户端，支持豆包/DeepSeek/OpenAI/通义等多模型切换

所有模型供应商只要兼容 OpenAI API 格式，都可以通过本模块调用。
配置在 settings.yaml 中：
    llm_model_params:
      model_name: 'doubao-1-5-pro-32k-250115'
      base_url: "https://ark.cn-beijing.volces.com/api/v3"
      api_key: 'your-api-key'
"""

import logging
from typing import List, Dict, Optional

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """大模型客户端 - 统一调用接口"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        """
        初始化 LLM 客户端

        Args:
            api_key: API 密钥，默认从配置读取
            base_url: API 地址，默认从配置读取
            model_name: 模型名称，默认从配置读取
        """
        self.api_key = api_key or str(settings.llm_model_params.api_key)
        self.base_url = base_url or str(settings.llm_model_params.base_url)
        self.model_name = model_name or str(settings.llm_model_params.model_name)

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        logger.info(f"LLM 客户端初始化完成: model={self.model_name}, base_url={self.base_url}")

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.8,
        max_tokens: int = 1000,
    ) -> str:
        """
        发送聊天请求

        Args:
            messages: 消息列表 [{"role": "system", "content": "..."}, ...]
            temperature: 温度参数，越高越随机
            max_tokens: 最大生成 token 数

        Returns:
            模型回复文本
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            logger.debug(f"LLM 回复: {content[:100]}...")
            return content.strip()
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return ""

    def chat_with_system(
        self,
        system_prompt: str,
        user_message: str,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.8,
        max_tokens: int = 1000,
    ) -> str:
        """
        带系统提示词的简化聊天接口

        Args:
            system_prompt: 系统提示词（人设）
            user_message: 用户消息
            history: 历史对话记录
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            模型回复文本
        """
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return self.chat(messages, temperature, max_tokens)

    def extract_memory(self, user_message: str) -> str:
        """
        从用户消息中提取值得记忆的信息

        Args:
            user_message: 用户消息

        Returns:
            提取的记忆摘要，如果没有值得记忆的信息则返回空字符串
        """
        prompt = (
            "请从以下用户消息中提取值得长期记忆的个人信息（如计划、偏好、事实等）。\n"
            "如果没有值得记忆的信息，回复'无'。\n"
            "只输出一句话摘要，不要解释。\n\n"
            f"用户消息: {user_message}"
        )
        result = self.chat_with_system(
            system_prompt="你是一个信息提取助手。",
            user_message=prompt,
            temperature=0.3,
            max_tokens=100,
        )
        if result and result.strip() != "无":
            return result.strip()
        return ""
