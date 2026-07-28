"""LLM 网关 - OpenAI 兼容客户端，支持豆包/DeepSeek/OpenAI/通义等多模型切换

所有模型供应商只要兼容 OpenAI API 格式，都可以通过本模块调用。
配置在 password.yaml 中：
    llm_model_params:
      model_name: 'doubao-seed-2-1-pro-260628'
      base_url: "https://ark.cn-beijing.volces.com/api/v3"
      api_key: 'your-api-key'
"""

import base64
import os
import logging
from typing import List, Dict, Optional, Any, Union

from openai import OpenAI

from config import settings
from utils.set_logger import get_logger

logger = get_logger()

# 消息内容类型：纯文本或多模态内容数组
ContentPart = Union[str, List[Dict[str, Any]]]


def _encode_image(image_path: str) -> str:
    """将本地图片编码为 base64 data URL"""
    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    if ext not in ("jpeg", "png", "gif", "webp"):
        ext = "jpeg"
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/{ext};base64,{data}"


class LLMClient:
    """大模型客户端 - 统一调用接口，支持多模态"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        # 兼容新旧配置：优先 text_llm_model_params，回退到旧 llm_model_params
        text_cfg = settings.get("TEXT_LLM_MODEL_PARAMS") or settings.get("llm_model_params")
        img_cfg = settings.get("IMG_LLM_MODEL_PARAMS") or text_cfg

        self.api_key = api_key or str(text_cfg.api_key)
        self.base_url = base_url or str(text_cfg.base_url)
        self.model_name = model_name or str(text_cfg.model_name)
        # 多模态使用的模型名（可能与文本模型不同）
        self.img_model_name = str(img_cfg.model_name)
        self.img_api_key = str(img_cfg.api_key)
        self.img_base_url = str(img_cfg.base_url)

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        # 多模态专用客户端（如果 base_url 或 api_key 不同）
        if self.img_base_url != self.base_url or self.img_api_key != self.api_key:
            self._img_client = OpenAI(api_key=self.img_api_key, base_url=self.img_base_url)
        else:
            self._img_client = self.client

        logger.info(f"LLM 客户端初始化完成: text_model={self.model_name}, img_model={self.img_model_name}, base_url={self.base_url}")

    def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.8,
        max_tokens: int = 1000,
    ) -> str:
        """
        发送聊天请求（支持多模态内容）

        Args:
            messages: 消息列表，content 可为纯文本或多模态内容数组
            temperature: 温度参数
            max_tokens: 最大生成 token 数

        Returns:
            模型回复文本
        """
        # 完整提示词写入日志（功能0）
        self._log_prompt(messages)

        try:
            logger.info(f"文本模型调用: model={self.model_name}")
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

    def _log_prompt(self, messages: List[Dict[str, Any]]):
        """将完整提示词写入日志，方便后期排查"""
        lines = []
        for m in messages:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, list):
                # 多模态内容，提取文本和图片标记
                parts = []
                for part in content:
                    if part.get("type") == "text":
                        parts.append(part["text"])
                    elif part.get("type") == "image_url":
                        parts.append("[图片]")
                content = " ".join(parts)
            lines.append(f"[{role}] {content}")
        full_prompt = "\n".join(lines)
        logger.info(f"===== 完整提示词 =====\n{full_prompt}\n=====================")

    def chat_with_system(
        self,
        system_prompt: str,
        user_message: str,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.8,
        max_tokens: int = 1000,
    ) -> str:
        """带系统提示词的简化聊天接口"""
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return self.chat(messages, temperature, max_tokens)

    def chat_multimodal(
        self,
        system_prompt: str,
        user_text: str,
        image_paths: Optional[List[str]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.8,
        max_tokens: int = 1000,
    ) -> str:
        """
        多模态聊天接口 - 支持文本+图片

        Args:
            system_prompt: 系统提示词
            user_text: 用户文本消息
            image_paths: 图片文件路径列表
            history: 历史对话记录
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            模型回复文本
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        if history:
            messages.extend(history)

        # 构建多模态 user 消息
        if image_paths:
            content: List[Dict[str, Any]] = [{"type": "text", "text": user_text}]
            valid_images = []
            for img_path in image_paths:
                if os.path.exists(img_path):
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": _encode_image(img_path)},
                    })
                    valid_images.append(img_path)
                else:
                    logger.warning(f"图片不存在，跳过: {img_path}")
            if not valid_images:
                # 没有有效图片，回退到纯文本
                logger.warning("没有有效图片，回退到纯文本调用")
                return self.chat_with_system(
                    system_prompt=system_prompt,
                    user_message=user_text,
                    history=history,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            messages.append({"role": "user", "content": content})

            # 多模态调用使用 img_model_name 和 _img_client
            self._log_prompt(messages)
            try:
                logger.info(f"多模态模型调用: model={self.img_model_name}")
                response = self._img_client.chat.completions.create(
                    model=self.img_model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content_resp = response.choices[0].message.content
                logger.debug(f"LLM 多模态回复: {content_resp[:100]}...")
                return content_resp.strip()
            except Exception as e:
                logger.error(f"LLM 多模态调用失败: {e}")
                return ""
        else:
            messages.append({"role": "user", "content": user_text})
            return self.chat(messages, temperature, max_tokens)

    def extract_memory(self, user_message: str, reply: str = "") -> str:
        """
        从对话中提取值得长期记忆的信息

        Args:
            user_message: 用户消息
            reply: 机器人回复（可选，提供更完整的上下文）

        Returns:
            提取的记忆摘要，如果没有值得记忆的信息则返回空字符串
        """
        dialog = f"用户: {user_message}"
        if reply:
            dialog += f"\n回复: {reply}"
        prompt = (
            "请从以下对话中提取值得长期记忆的个人信息（如计划、偏好、习惯、事实、生日等）。\n"
            "如果没有值得记忆的信息，回复'无'。\n"
            "只输出一句话摘要，不要解释。\n\n"
            f"{dialog}"
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
