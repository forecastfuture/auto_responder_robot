"""回复决策器测试 - 测试回复判断和@清理逻辑"""

import random
import pytest

from agent.planner import Planner


@pytest.fixture
def planner():
    """创建测试用决策器"""
    return Planner(
        bot_name="管家",
        reply_probability=0.15,
        keywords=["AI", "GPT", "机器人", "管家", "三月"],
    )


class TestPlanner:
    """Planner 测试"""

    def test_at_bot_should_reply(self, planner):
        """被@时应该回复"""
        assert planner.should_reply("你好", is_at_bot=True) is True

    def test_keyword_should_reply(self, planner):
        """包含关键词时应该回复"""
        assert planner.should_reply("最近AI发展怎么样？") is True
        assert planner.should_reply("GPT模型哪个好？") is True
        assert planner.should_reply("你是机器人吗？") is True
        assert planner.should_reply("管家，帮我看看") is True
        assert planner.should_reply("三月你在吗") is True

    def test_keyword_case_insensitive(self, planner):
        """关键词不区分大小写"""
        assert planner.should_reply("ai是什么") is True
        assert planner.should_reply("gpt怎么用") is True

    def test_normal_message_probability(self, planner):
        """普通消息按概率回复"""
        random.seed(42)
        results = [planner.should_reply("今天天气不错") for _ in range(100)]
        # 15% 概率，100次中应该有回复（概率很高），但不一定全是
        assert True in results
        assert False in results
        # 概率应该在合理范围内
        reply_count = sum(results)
        assert 5 <= reply_count <= 35  # 允许较大偏差

    def test_empty_message_no_reply(self, planner):
        """空消息不回复"""
        assert planner.should_reply("") is False
        assert planner.should_reply("   ") is False
        assert planner.should_reply(None) is False

    def test_no_keyword_no_at_low_probability(self, planner):
        """没有关键词且没被@时概率较低"""
        random.seed(0)
        results = [planner.should_reply("吃饭了吗") for _ in range(100)]
        reply_count = sum(results)
        assert reply_count < 35  # 不应该回复太多

    def test_check_at_bot(self, planner):
        """测试@检测"""
        assert planner.check_at_bot("@管家 你好") is True
        assert planner.check_at_bot("@ 管家 你好") is True
        assert planner.check_at_bot("管家你好") is False
        assert planner.check_at_bot("@张三 你好") is False  # @别人不算

    def test_clean_at_mention_basic(self, planner):
        """测试清理@提及"""
        result = planner.clean_at_mention("@管家 你好")
        assert result == "你好"

        result = planner.clean_at_mention("@所有人 今天开会")
        assert result == "今天开会"

    def test_clean_at_mention_multiple(self, planner):
        """测试清理多个@"""
        result = planner.clean_at_mention("@张三 @管家 你们好")
        assert result == "你们好"

    def test_clean_at_mention_no_at(self, planner):
        """没有@时不变"""
        result = planner.clean_at_mention("今天天气真好")
        assert result == "今天天气真好"

    def test_clean_at_mention_all(self, planner):
        """测试清理@all"""
        result = planner.clean_at_mention("@all 大家注意")
        assert result == "大家注意"
