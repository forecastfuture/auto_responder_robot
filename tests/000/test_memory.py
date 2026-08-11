"""记忆系统测试 - 测试对话历史和长期记忆的存储与检索"""

import os
import tempfile
import pytest

from agent.memory import MemoryManager


@pytest.fixture
def memory():
    """创建临时记忆管理器"""
    db_path = os.path.join(tempfile.mkdtemp(), "test_memory.db")
    mgr = MemoryManager(db_path=db_path)
    yield mgr


class TestMemoryManager:
    """MemoryManager 测试"""

    def test_add_and_get_message(self, memory):
        """测试添加和获取消息"""
        memory.add_message("张三", "朋友群", "你好", "user")
        memory.add_message("管家", "朋友群", "你好呀", "assistant")

        history = memory.get_recent_history("朋友群", limit=10)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert "张三" in history[0]["content"]
        assert "你好" in history[0]["content"]
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "你好呀"

    def test_message_order(self, memory):
        """测试消息按时间顺序返回"""
        memory.add_message("张三", "朋友群", "第一条", "user")
        memory.add_message("管家", "朋友群", "第二条", "assistant")
        memory.add_message("李四", "朋友群", "第三条", "user")

        history = memory.get_recent_history("朋友群", limit=3)
        assert len(history) == 3
        assert "第一条" in history[0]["content"]
        assert "第三条" in history[2]["content"]

    def test_limit_messages(self, memory):
        """测试限制返回数量"""
        for i in range(20):
            memory.add_message("张三", "朋友群", f"消息{i}", "user")

        history = memory.get_recent_history("朋友群", limit=5)
        assert len(history) == 5
        # 应该返回最近的 5 条
        assert "消息19" in history[-1]["content"]
        assert "消息15" in history[0]["content"]

    def test_different_groups(self, memory):
        """测试不同群的消息隔离"""
        memory.add_message("张三", "朋友群", "朋友群消息", "user")
        memory.add_message("李四", "技术群", "技术群消息", "user")

        friend_history = memory.get_recent_history("朋友群", limit=10)
        tech_history = memory.get_recent_history("技术群", limit=10)

        assert len(friend_history) == 1
        assert len(tech_history) == 1
        assert "朋友群消息" in friend_history[0]["content"]
        assert "技术群消息" in tech_history[0]["content"]

    def test_add_and_get_memory(self, memory):
        """测试添加和获取长期记忆"""
        memory.add_memory("张三", "喜欢旅游", importance=0.8)
        memory.add_memory("张三", "计划去上海", importance=0.9)
        memory.add_memory("李四", "喜欢编程", importance=0.7)

        zhang_memories = memory.get_memories("张三")
        li_memories = memory.get_memories("李四")

        assert len(zhang_memories) == 2
        assert len(li_memories) == 1
        # 按重要性排序，"计划去上海" (0.9) 应该在前
        assert "计划去上海" in zhang_memories[0]
        assert "喜欢编程" in li_memories[0]

    def test_memory_context(self, memory):
        """测试记忆上下文构建"""
        memory.add_memory("张三", "喜欢旅游")
        memory.add_memory("张三", "下个月去上海")

        context = memory.build_memory_context("张三")
        assert "张三" in context
        assert "旅游" in context
        assert "上海" in context

    def test_empty_memory_context(self, memory):
        """测试无记忆时的上下文"""
        context = memory.build_memory_context("不存在的人")
        assert context == ""

    def test_empty_history(self, memory):
        """测试空群的历史"""
        history = memory.get_recent_history("空群", limit=10)
        assert len(history) == 0
