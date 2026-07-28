"""微信机器人 - 基于 pywechat (pyweixin 模块) 的微信 PC 客户端自动化

pywechat 通过 pywinauto 自动化 Windows 微信客户端实现消息收发。
使用前需要:
    1. Windows 系统上运行微信 PC 客户端（版本 4.1.x）
    2. pip install pywechat127
    3. 微信客户端保持登录状态

主要功能:
    - 发送消息到群/好友
    - 监听群消息（通过轮询会话列表新消息）
    - 获取会话列表
    - 拉取指定会话最近N条消息（含图片）
"""

from typing import List, Optional, Any

from utils.set_logger import get_logger

logger = get_logger()

# 图片消息类型关键词
_IMAGE_TYPES = {"图片", "image", "[图片]", "[image]"}


class WeChatMessage:
    """微信消息封装类"""

    def __init__(
        self,
        sender: str = "",
        content: str = "",
        chat: str = "",
        msg_type: str = "text",
        image_path: str = "",
        raw: Any = None,
    ):
        self.sender = sender
        self.content = content
        self.chat = chat
        self.msg_type = msg_type
        self.image_path = image_path  # 图片消息的本地路径（如有）
        self.raw = raw

    def __repr__(self):
        return (
            f"WeChatMessage(sender='{self.sender}', chat='{self.chat}', "
            f"content='{self.content[:30]}...')"
        )

    @property
    def is_image(self) -> bool:
        """是否为图片消息"""
        return self.msg_type in _IMAGE_TYPES or bool(self.image_path)

    @classmethod
    def from_pyweixin(cls, msg_dict: dict, chat_name: str = "") -> "WeChatMessage":
        """从 pyweixin 消息字典转换为 WeChatMessage"""
        sender = str(msg_dict.get("消息发送人", "") or "")
        content = str(msg_dict.get("消息内容", "") or "")
        msg_type = str(msg_dict.get("消息类型", "text") or "text")
        # 尝试获取图片路径（pyweixin 可能在不同字段中返回图片路径）
        image_path = (
            str(msg_dict.get("图片路径", "") or "")
            or str(msg_dict.get("image_path", "") or "")
            or str(msg_dict.get("文件路径", "") or "")
        )
        # 如果消息类型是图片但内容为空，给个占位符
        if msg_type in _IMAGE_TYPES and not content:
            content = "[图片]"
        return cls(
            sender=sender,
            content=content,
            chat=chat_name,
            msg_type=msg_type,
            image_path=image_path,
            raw=msg_dict,
        )


class WeChatBot:
    """微信机器人 - pyweixin 封装

    基于 pywechat127 包的 pyweixin 模块，适配微信 4.1.x 客户端。
    所有 UI 自动化操作均通过 pywinauto 实现，不涉及逆向 Hook。
    """

    def __init__(self, listen_groups: Optional[List[str]] = None):
        self._initialized = False
        self.listen_groups = (
            [g.strip() for g in listen_groups if g and g.strip()]
            if listen_groups else None
        )
        self._seen_messages: set = set()
        self._session_snapshot: dict = {}
        self._first_scan: bool = True
        self._my_name: str = ""
        self._sent_contents: set = set()
        self._sent_contents_ordered: list = []

    def init_wechat(self) -> bool:
        """初始化微信连接，验证客户端已运行并登录"""
        try:
            from pyweixin import Tools, GlobalConfig

            GlobalConfig.close_weixin = False
            GlobalConfig.is_maximize = False
            GlobalConfig.search_pages = 0

            info = Tools.about_weixin()
            self._initialized = True
            logger.info(f"微信连接成功: {info}")

            try:
                from pyweixin import Contacts
                my_info = Contacts.check_my_info(close_weixin=False)
                self._my_name = my_info.get("昵称", "")
                if self._my_name:
                    logger.info(f"当前用户昵称: {self._my_name}")
            except Exception as e:
                logger.warning(f"获取用户昵称失败，将无法过滤自己发的消息: {e}")

            return True
        except ImportError:
            logger.error(
                "pywechat 未安装，请运行: pip install pywechat127 --user --no-cache-dir\n"
                "同时确保 Windows 上已运行微信 PC 客户端（4.1.x）并保持登录状态。"
            )
            return False
        except Exception as e:
            logger.error(f"微信初始化失败: {e}")
            return False

    def _is_self_message(self, sender: str, content: str) -> bool:
        """判断消息是否为自己发送的（发送者名称匹配 + 已回复内容匹配）"""
        s = sender.strip()
        if s == "你":
            return True
        if self._my_name:
            my = self._my_name.strip()
            if s == my or my in s:
                return True
        content_norm = " ".join(content.strip().split())
        if content_norm:
            for sent in self._sent_contents:
                if " ".join(sent.strip().split()) == content_norm:
                    return True
        return False

    def send_group_message(self, group_name: str, message: str) -> bool:
        """发送消息到群（或好友）"""
        if not self._initialized:
            logger.error("微信未初始化，无法发送消息")
            return False

        target = group_name.strip()
        if not target:
            logger.error("发送目标为空，拒绝发送")
            return False

        if self.listen_groups and target not in self.listen_groups:
            logger.warning(f"目标会话 '{target}' 不在监听白名单内，拒绝发送")
            return False

        try:
            from pyweixin import Messages

            Messages.send_messages_to_friend(
                friend=target, messages=[message], close_weixin=False,
            )
            content = message.strip()
            self._sent_contents.add(content)
            self._sent_contents_ordered.append(content)
            while len(self._sent_contents_ordered) > 200:
                old = self._sent_contents_ordered.pop(0)
                self._sent_contents.discard(old)
            logger.info(f"消息已发送到 '{target}': {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"发送消息到 '{target}' 失败: {e}")
            return False

    def send_message(self, who: str, message: str) -> bool:
        """发送消息（通用接口，群或好友均可）"""
        return self.send_group_message(who, message)

    def get_recent_messages(self, chat_name: str, count: int = 5) -> List[WeChatMessage]:
        """
        拉取指定会话最近的 N 条消息（含图片）

        Args:
            chat_name: 会话名称（群名或好友名）
            count: 拉取条数

        Returns:
            WeChatMessage 列表，按时间正序排列（最旧的在前）
        """
        if not self._initialized:
            return []
        try:
            from pyweixin import Messages

            msg_list = Messages.pull_messages(
                friend=chat_name, number=count, close_weixin=False,
            )
            if not msg_list:
                return []
            # pull_messages 返回最新在前，反转为正序
            msgs = [WeChatMessage.from_pyweixin(m, chat_name) for m in reversed(msg_list)]
            logger.info(f"从 '{chat_name}' 拉取到 {len(msgs)} 条消息")
            for m in msgs:
                kind = "图片" if m.is_image else "文本"
                logger.debug(f"  [{kind}] {m.sender}: {m.content[:50]}")
            return msgs
        except Exception as e:
            logger.error(f"拉取 '{chat_name}' 最近消息失败: {e}")
            return []

    def get_last_message(self, chat_name: str) -> Optional[WeChatMessage]:
        """
        获取指定会话最后一条他人消息（用于测试）

        Args:
            chat_name: 会话名称

        Returns:
            最后一条非自己发的消息，没有则返回 None
        """
        msgs = self.get_recent_messages(chat_name, count=5)
        for m in reversed(msgs):
            if self._is_self_message(m.sender, m.content):
                continue
            return m
        return None

    def get_messages(self) -> List[WeChatMessage]:
        """
        获取新消息列表

        通过会话列表快照对比检测新消息，对有变化的会话拉取最近消息。
        已自动过滤自身消息和已处理消息（保证每条只回复一次）。

        Returns:
            WeChatMessage 列表
        """
        if not self._initialized:
            return []

        try:
            from pyweixin import Messages

            sessions = Messages.dump_sessions(chat_only=True, close_weixin=False)
            if not sessions:
                return []

            if self._first_scan:
                for s in sessions:
                    if s and s[0]:
                        friend = s[0]
                        ts = s[1] if len(s) > 1 else ""
                        content = s[2] if len(s) > 2 else ""
                        self._session_snapshot[friend] = f"{ts}|{content}"
                self._first_scan = False
                logger.info(f"首次扫描完成，建立 {len(self._session_snapshot)} 个会话基线")
                return []

            changed_sessions = []
            for s in sessions:
                if not s or not s[0]:
                    continue
                friend = str(s[0]).strip()
                if not friend:
                    continue
                if self.listen_groups and friend not in self.listen_groups:
                    continue
                ts = s[1] if len(s) > 1 else ""
                content = s[2] if len(s) > 2 else ""
                current_sig = f"{ts}|{content}"
                prev_sig = self._session_snapshot.get(friend)
                if prev_sig is None or current_sig != prev_sig:
                    changed_sessions.append(friend)
                self._session_snapshot[friend] = current_sig

            if not changed_sessions:
                return []

            logger.info(f"检测到 {len(changed_sessions)} 个会话有新消息: {changed_sessions}")

            messages = []
            for friend in changed_sessions:
                try:
                    msg_list = Messages.pull_messages(
                        friend=friend, number=5, close_weixin=False,
                    )
                    if not msg_list:
                        continue
                    for msg_dict in msg_list:
                        msg = WeChatMessage.from_pyweixin(msg_dict, chat_name=friend)
                        # 跳过空文本且非图片的消息
                        if not msg.content.strip() and not msg.is_image:
                            continue
                        if self._is_self_message(msg.sender, msg.content):
                            continue
                        msg_key = (
                            f"{' '.join(msg.sender.strip().split())}|"
                            f"{' '.join(msg.content.strip().split())}|"
                            f"{msg.chat.strip()}"
                        )
                        if msg_key in self._seen_messages:
                            continue
                        self._seen_messages.add(msg_key)
                        if len(self._seen_messages) > 1000:
                            self._seen_messages.pop()
                        messages.append(msg)
                except Exception as e:
                    logger.error(f"拉取 '{friend}' 的消息失败: {e}")

            if messages:
                logger.info(f"共获取 {len(messages)} 条新消息")
            return messages

        except Exception as e:
            logger.error(f"获取消息失败: {e}", exc_info=True)
            return []

    def get_all_chats(self) -> List[str]:
        """获取当前所有聊天窗口名称"""
        if not self._initialized:
            return []
        try:
            from pyweixin import Messages

            sessions = Messages.dump_sessions(close_weixin=False)
            if sessions:
                return [s[0] for s in sessions if s and s[0]]
            return []
        except Exception as e:
            logger.error(f"获取聊天列表失败: {e}")
            return []

    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized
