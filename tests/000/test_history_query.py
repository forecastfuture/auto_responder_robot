"""历史对话查询测试

测试项:
    1. 按关键词搜索历史记录
    2. 指定会话名称搜索
    3. 搜索不存在的关键词返回空
    4. 搜索结果包含完整字段

运行: python -m pytest tests/000/test_history_query.py -v -s
"""

import os
import tempfile
import pytest

from agent.memory import MemoryManager


@pytest.fixture
def memory():
    """创建临时记忆管理器并填入测试数据"""
    db_path = os.path.join(tempfile.mkdtemp(), "test_history.db")
    mgr = MemoryManager(db_path=db_path)

    # 填入测试数据
    mgr.add_message("三月", "二人世界", "今天重庆渝北天气怎么样", "user")
    mgr.add_message("twenty", "二人世界", "我来查查天气", "assistant")
    mgr.add_message("Angel", "二人世界", "巴厘岛旅游攻略分享", "user")
    mgr.add_message("三月", "测试群", "今天吃什么好", "user")
    mgr.add_message("twenty", "测试群", "牛肉干好吃", "assistant")
    mgr.add_message("三月", "二人世界", "下周去巴厘岛玩", "user")

    yield mgr


class TestHistoryQuery:
    """历史记录搜索测试"""

    def test_search_by_keyword(self, memory):
        """测试按关键词搜索"""
        results = memory.search_history("天气")
        print(f"\n--- 搜索'天气' ---\n{results}\n")
        assert len(results) >= 1
        assert any("天气" in r["content"] for r in results)

    def test_search_by_keyword_bali(self, memory):
        """测试搜索巴厘岛相关记录"""
        results = memory.search_history("巴厘岛")
        print(f"\n--- 搜索'巴厘岛' ---\n{results}\n")
        assert len(results) >= 2  # 有两条包含"巴厘岛"
        for r in results:
            assert "巴厘岛" in r["content"]

    def test_search_with_chat_name(self, memory):
        """测试指定会话名称搜索"""
        results = memory.search_history("巴厘岛", chat_name="二人世界")
        print(f"\n--- 二人世界搜索'巴厘岛' ---\n{results}\n")
        assert len(results) >= 2
        for r in results:
            assert r["chat"] == "二人世界"

    def test_search_cross_chat_isolation(self, memory):
        """测试不同会话消息隔离"""
        # "牛肉干"只在测试群
        results = memory.search_history("牛肉干", chat_name="二人世界")
        assert len(results) == 0, "二人世界中不应有'牛肉干'记录"

        results_all = memory.search_history("牛肉干")
        assert len(results_all) == 1
        assert results_all[0]["chat"] == "测试群"

    def test_search_nonexistent_keyword(self, memory):
        """测试搜索不存在的关键词"""
        results = memory.search_history("不存在的关键词xyz")
        assert len(results) == 0

    def test_search_result_fields(self, memory):
        """测试搜索结果包含完整字段"""
        results = memory.search_history("天气")
        assert len(results) > 0
        r = results[0]
        assert "sender" in r
        assert "chat" in r
        assert "content" in r
        assert "role" in r
        assert "timestamp" in r

    def test_search_empty_keyword(self, memory):
        """测试空关键词搜索"""
        results = memory.search_history("")
        assert len(results) == 0

    def test_search_all_chats(self, memory):
        """测试不指定会话搜索全部"""
        results = memory.search_history("twenty")
        # twenty 的回复有2条
        assert len(results) >= 2


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "-s"])
