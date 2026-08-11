"""main.py 辅助函数测试 - 测试提示词构建逻辑"""

import os
import sys
import tempfile
from datetime import datetime

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from unittest.mock import patch

from main import build_time_prompt, build_context_prompt, build_memory_prompt
from wechat.bot import WeChatMessage
from agent.memory import MemoryManager


class TestBuildTimePrompt:
    """测试实时时间提示词构建"""

    def test_time_prompt_contains_date(self):
        """测试时间提示词包含年月日"""
        prompt = build_time_prompt()
        now = datetime.now()
        # 手动拼接，避免 strftime 在 Windows 上不支持中文
        date_str = f"{now.year}年{now.month:02d}月{now.day:02d}日"
        assert date_str in prompt

    def test_time_prompt_contains_time(self):
        """测试时间提示词包含时分秒"""
        prompt = build_time_prompt()
        assert "时" in prompt or ":" in prompt

    def test_time_prompt_contains_weekday(self):
        """测试时间提示词包含星期"""
        prompt = build_time_prompt()
        assert "星期" in prompt

    def test_time_prompt_format(self):
        """测试时间提示词格式"""
        prompt = build_time_prompt()
        assert "当前时间" in prompt


class TestBuildContextPrompt:
    """测试对话上下文提示词构建"""

    def test_empty_context(self):
        """测试空上下文"""
        current = WeChatMessage(sender="三月", content="你好", chat="群")
        prompt = build_context_prompt([], current)
        assert prompt == ""

    def test_text_context(self):
        """测试文本消息上下文"""
        msgs = [
            WeChatMessage(sender="三月", content="今天天气不错", chat="群"),
            WeChatMessage(sender="angel", content="是啊", chat="群"),
        ]
        current = WeChatMessage(sender="三月", content="今天天气不错", chat="群")
        prompt = build_context_prompt(msgs, current)
        assert "最近对话上下文" in prompt
        assert "三月" in prompt
        assert "angel" in prompt

    def test_image_in_context(self):
        """测试图片消息在上下文中标记"""
        msgs = [
            WeChatMessage(sender="angel", content="[图片]", chat="群", msg_type="图片"),
        ]
        current = WeChatMessage(sender="test", content="看看", chat="群")
        prompt = build_context_prompt(msgs, current)
        assert "[图片]" in prompt

    def test_current_message_tagged(self):
        """测试当前消息被标记"""
        current = WeChatMessage(sender="三月", content="你好", chat="群")
        msgs = [current]
        prompt = build_context_prompt(msgs, current)
        assert "当前消息" in prompt


class TestBuildMemoryPrompt:
    """测试历史对话记忆提示词构建"""

    @pytest.fixture
    def memory(self):
        """创建临时记忆管理器"""
        db_path = os.path.join(tempfile.mkdtemp(), "test_memory.db")
        return MemoryManager(db_path=db_path)

    def test_empty_memory(self, memory):
        """测试无记忆时返回空"""
        prompt = build_memory_prompt(memory, "测试群")
        assert prompt == ""

    def test_with_history(self, memory):
        """测试有历史记录时构建记忆提示词"""
        memory.add_message("张三", "测试群", "你好", "user")
        memory.add_message("twenty", "测试群", "你好呀", "assistant")

        prompt = build_memory_prompt(memory, "测试群")
        assert "历史对话记忆" in prompt
        assert "你好" in prompt
        assert "你好呀" in prompt

    def test_different_group_isolation(self, memory):
        """测试不同群记忆隔离"""
        memory.add_message("张三", "A群", "A消息", "user")
        memory.add_message("李四", "B群", "B消息", "user")

        prompt_a = build_memory_prompt(memory, "A群")
        prompt_b = build_memory_prompt(memory, "B群")
        assert "A消息" in prompt_a
        assert "B消息" not in prompt_a
        assert "B消息" in prompt_b
