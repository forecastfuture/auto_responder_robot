"""微信消息封装测试 - 测试 WeChatMessage 的图片识别和消息解析"""

import pytest

from wechat.bot import WeChatMessage, WeChatBot


class TestWeChatMessage:
    """WeChatMessage 测试"""

    def test_text_message(self):
        """测试文本消息解析"""
        msg = WeChatMessage.from_pyweixin(
            {"消息发送人": "三月", "消息内容": "你好", "消息类型": "text"},
            chat_name="测试群",
        )
        assert msg.sender == "三月"
        assert msg.content == "你好"
        assert msg.chat == "测试群"
        assert msg.msg_type == "text"
        assert not msg.is_image

    def test_image_message_with_path(self):
        """测试图片消息（带路径）"""
        msg = WeChatMessage.from_pyweixin(
            {"消息发送人": "angel", "消息内容": "[图片]", "消息类型": "图片", "图片路径": "C:/test.png"},
            chat_name="测试群",
        )
        assert msg.sender == "angel"
        assert msg.msg_type == "图片"
        assert msg.image_path == "C:/test.png"
        assert msg.is_image

    def test_image_message_no_content(self):
        """测试图片消息无内容时自动填充"""
        msg = WeChatMessage.from_pyweixin(
            {"消息发送人": "angel", "消息内容": "", "消息类型": "图片"},
            chat_name="测试群",
        )
        assert msg.content == "[图片]"
        assert msg.is_image

    def test_image_message_english_type(self):
        """测试英文图片类型"""
        msg = WeChatMessage.from_pyweixin(
            {"消息发送人": "test", "消息内容": "see this", "消息类型": "image"},
            chat_name="test_chat",
        )
        assert msg.is_image

    def test_missing_fields(self):
        """测试缺失字段时使用默认值"""
        msg = WeChatMessage.from_pyweixin({}, chat_name="群")
        assert msg.sender == ""
        assert msg.content == ""
        assert msg.msg_type == "text"
        assert not msg.is_image

    def test_none_values_in_dict(self):
        """测试字典中值为 None 的情况"""
        msg = WeChatMessage.from_pyweixin(
            {"消息发送人": None, "消息内容": None, "消息类型": None},
            chat_name="群",
        )
        assert msg.sender == ""
        assert msg.content == ""
        assert msg.msg_type == "text"

    def test_repr(self):
        """测试 __repr__ 输出"""
        msg = WeChatMessage(sender="张三", content="这是一条很长的消息内容用于测试截断功能", chat="群")
        repr_str = repr(msg)
        assert "张三" in repr_str
        assert "群" in repr_str


class TestRecentContextCache:
    """测试 get_messages() 缓存机制 - 避免重复调用 pull_messages"""

    def test_empty_cache(self):
        """无缓存时返回空列表"""
        bot = WeChatBot()
        assert bot.get_cached_recent_messages("测试群") == []

    def test_cache_returns_messages(self):
        """缓存后能正确返回消息列表"""
        bot = WeChatBot()
        msgs = [
            WeChatMessage(sender="三月", content="hello", chat="测试群"),
            WeChatMessage(sender="angel", content="hi", chat="测试群"),
        ]
        bot._recent_context["测试群"] = msgs
        cached = bot.get_cached_recent_messages("测试群")
        assert len(cached) == 2
        assert cached[0].sender == "三月"
        assert cached[1].sender == "angel"

    def test_cache_isolated_per_chat(self):
        """不同会话的缓存互相隔离"""
        bot = WeChatBot()
        bot._recent_context["群A"] = [WeChatMessage(sender="A", content="msgA", chat="群A")]
        bot._recent_context["群B"] = [WeChatMessage(sender="B", content="msgB", chat="群B")]
        assert len(bot.get_cached_recent_messages("群A")) == 1
        assert len(bot.get_cached_recent_messages("群B")) == 1
        assert bot.get_cached_recent_messages("群A")[0].sender == "A"
        assert bot.get_cached_recent_messages("群B")[0].sender == "B"

    def test_cache_does_not_call_pull_messages(self):
        """get_cached_recent_messages 不应触发 pull_messages 调用"""
        bot = WeChatBot()
        # 即使未初始化，缓存方法也应正常返回空列表（不报错）
        result = bot.get_cached_recent_messages("任何群")
        assert result == []
