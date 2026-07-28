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

import os
from typing import List, Optional, Any

from utils.set_logger import get_logger

logger = get_logger()

# 图片消息类型关键词
_IMAGE_TYPES = {"图片", "image", "[图片]", "[image]"}

# 图片保存目录（data/images/）
_IMAGE_SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "images")


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
        self._recent_context: dict = {}  # {chat_name: [WeChatMessage, ...]} 缓存最近拉取的消息（按时间正序）

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

    def _save_recent_images(self, friend: str, count: int) -> List[str]:
        """
        保存与指定会话最近的 N 张图片到本地

        pyweixin 的 pull_messages 只返回消息文本，不含图片文件。
        此方法调用 Messages.save_media 从聊天记录中保存图片截图。
        保存的文件按 newest first 排序（index 0 = 最新图片）。

        Args:
            friend: 会话名称
            count: 需要保存的图片数量

        Returns:
            保存的图片文件路径列表（newest first），失败返回空列表
        """
        if not self._initialized or count <= 0:
            return []
        try:
            from pyweixin import Messages

            os.makedirs(_IMAGE_SAVE_DIR, exist_ok=True)

            # save_media 保存文件名格式: "与{friend}的聊天图片{num}.png" (num=1 是最新)
            Messages.save_media(
                friend=friend,
                number=count,
                target_folder=_IMAGE_SAVE_DIR,
                close_weixin=False,
            )

            # 查找刚保存的图片文件
            prefix = f"与{friend}的聊天图片"
            saved_files = []
            for i in range(1, count + 1):
                path = os.path.join(_IMAGE_SAVE_DIR, f"{prefix}{i}.png")
                if os.path.exists(path):
                    saved_files.append(path)

            # 清理旧图片（只保留本次保存的）
            for f_name in os.listdir(_IMAGE_SAVE_DIR):
                if f_name.startswith(prefix) and f_name.endswith(".png"):
                    full_path = os.path.join(_IMAGE_SAVE_DIR, f_name)
                    if full_path not in saved_files:
                        try:
                            os.remove(full_path)
                        except Exception:
                            pass

            if saved_files:
                logger.info(f"保存了 {len(saved_files)} 张图片: {saved_files}")
            return saved_files
        except Exception as e:
            logger.error(f"保存图片失败: {e}")
            return []

    def _attach_image_paths(self, msgs: List[WeChatMessage], friend: str) -> None:
        """
        为图片消息关联本地图片文件路径

        检测 msgs 中的图片消息，调用 save_media 保存最近图片，
        然后将保存的文件路径按时间倒序映射到图片消息对象。

        Args:
            msgs: 按时间正序排列的消息列表（最旧的在前）
            friend: 会话名称
        """
        image_msgs = [m for m in msgs if m.is_image]
        if not image_msgs:
            return
        saved_paths = self._save_recent_images(friend, len(image_msgs))
        if not saved_paths:
            logger.warning(f"未能保存 '{friend}' 的图片，将回退到纯文本处理")
            return
        # saved_paths: newest first (index 0 = 最新)
        # image_msgs: 按时间正序 (最后一个 = 最新)
        # 反向遍历 image_msgs，从最新的开始匹配
        for i, img_msg in enumerate(reversed(image_msgs)):
            if i < len(saved_paths):
                img_msg.image_path = saved_paths[i]
                logger.info(f"图片消息已关联: {img_msg.sender} -> {saved_paths[i]}")

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

    def get_cached_recent_messages(self, chat_name: str) -> List[WeChatMessage]:
        """
        获取上次 get_messages() 拉取的最近消息（避免重复调用 pull_messages）

        get_messages() 内部已调用 pull_messages 拉取5条消息并缓存，
        此方法直接返回缓存结果，不触发额外的 UI 自动化操作。

        Args:
            chat_name: 会话名称

        Returns:
            WeChatMessage 列表（按时间正序），没有缓存则返回空列表
        """
        return self._recent_context.get(chat_name, [])

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

            # 检测图片消息，保存图片并关联本地路径
            self._attach_image_paths(msgs, chat_name)

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
                    # 创建 WeChatMessage 列表（按时间正序），复用同一批对象
                    msgs_chrono = [
                        WeChatMessage.from_pyweixin(m, chat_name=friend)
                        for m in reversed(msg_list)
                    ]

                    # 检测图片消息，保存图片并关联本地路径
                    self._attach_image_paths(msgs_chrono, friend)

                    # 缓存拉取的最近消息（按时间正序），供 main.py 作为上下文使用
                    self._recent_context[friend] = list(msgs_chrono)

                    # 从同一批对象中筛选新消息（按时间正序遍历）
                    for msg in msgs_chrono:
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
