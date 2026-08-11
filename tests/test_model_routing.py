"""模型路由测试 - 验证文本消息用文本模型，图片消息用多模态模型

用 mock 替换 OpenAI 客户端，不发起真实 API 请求。
"""

import os
import base64
import tempfile
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm.client import LLMClient


def _make_fake_response(text="test reply"):
    """构建模拟的 OpenAI 响应对象"""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    return resp


def _make_tiny_png(path):
    """创建一个 1x1 像素 PNG 文件用于测试"""
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    with open(path, "wb") as f:
        f.write(png_data)


class TestModelRouting:
    """验证文本/图片消息分别使用正确的模型"""

    @patch("llm.client.OpenAI")
    def test_config_loads_two_different_models(self, mock_openai_cls):
        """配置应加载两个不同的模型名"""
        llm = LLMClient()
        assert llm.model_name != llm.img_model_name, (
            f"文本模型和图片模型不应相同: text={llm.model_name}, img={llm.img_model_name}"
        )

    @patch("llm.client.OpenAI")
    def test_text_chat_uses_text_model(self, mock_openai_cls):
        """chat() 应使用 text_llm_model_params 配置的模型"""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_fake_response("hello")

        llm = LLMClient()
        llm.chat([{"role": "user", "content": "你好"}])

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == llm.model_name
        assert call_kwargs["model"] != llm.img_model_name

    @patch("llm.client.OpenAI")
    def test_chat_with_system_uses_text_model(self, mock_openai_cls):
        """chat_with_system() 应使用文本模型"""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_fake_response("hi")

        llm = LLMClient()
        llm.chat_with_system("you are a bot", "hello")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == llm.model_name

    @patch("llm.client.OpenAI")
    def test_image_chat_uses_img_model(self, mock_openai_cls):
        """chat_multimodal() 有图片时应使用多模态模型"""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_fake_response("it's a cat")

        llm = LLMClient()

        # 创建临时图片
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img_path = f.name
        _make_tiny_png(img_path)

        try:
            llm.chat_multimodal(
                system_prompt="you are a bot",
                user_text="describe image",
                image_paths=[img_path],
            )

            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["model"] == llm.img_model_name
            assert call_kwargs["model"] != llm.model_name
        finally:
            os.unlink(img_path)

    @patch("llm.client.OpenAI")
    def test_multimodal_no_image_uses_text_model(self, mock_openai_cls):
        """chat_multimodal() 无图片时应回退到文本模型"""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_fake_response("ok")

        llm = LLMClient()
        llm.chat_multimodal(
            system_prompt="you are a bot",
            user_text="hello",
            image_paths=None,
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == llm.model_name

    @patch("llm.client.OpenAI")
    def test_multimodal_invalid_image_falls_back_to_text(self, mock_openai_cls):
        """chat_multimodal() 图片文件不存在时应回退到文本模型"""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_fake_response("ok")

        llm = LLMClient()
        llm.chat_multimodal(
            system_prompt="you are a bot",
            user_text="hello",
            image_paths=["/nonexistent/path.png"],
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == llm.model_name

    @patch("llm.client.OpenAI")
    def test_extract_memory_uses_text_model(self, mock_openai_cls):
        """extract_memory() 应使用文本模型而非多模态模型"""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_fake_response("无")

        llm = LLMClient()
        llm.extract_memory("你好", "你好呀")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == llm.model_name


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
