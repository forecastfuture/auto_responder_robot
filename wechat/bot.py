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
"""

from typing import List, Optional, Any, Dict

from utils.set_logger import get_logger

logger = get_logger()


class WeChatMessage:
    """微信消息封装类"""

    def __init__(
        self,
        sender: str = "",
        content: str = "",
        chat: str = "",
        msg_type: str = "text",
        raw: Any = None,
    ):
        self.sender = sender
        self.content = content
        self.chat = chat
        self.msg_type = msg_type
        self.raw = raw
        self.history: List[Dict[str, str]] = []  # 最近对话上下文（结构化多轮消息，从聊天窗口实时拉取）

    def __repr__(self):
        return (
            f"WeChatMessage(sender='{self.sender}', chat='{self.chat}', "
            f"content='{self.content[:30]}...')"
        )

    @classmethod
    def from_pyweixin(cls, msg_dict: dict, chat_name: str = "") -> "WeChatMessage":
        """从 pyweixin 消息字典转换为 WeChatMessage"""
        sender = str(msg_dict.get("消息发送人", "") or "")
        content = str(msg_dict.get("消息内容", "") or "")
        msg_type = str(msg_dict.get("消息类型", "text") or "text")
        return cls(sender=sender, content=content, chat=chat_name, msg_type=msg_type, raw=msg_dict)


class WeChatBot:
    """微信机器人 - pyweixin 封装

    基于 pywechat127 包的 pyweixin 模块，适配微信 4.1.x 客户端。
    所有 UI 自动化操作均通过 pywinauto 实现，不涉及逆向 Hook。
    """

    def __init__(self, listen_groups: Optional[List[str]] = None):
        """
        Args:
            listen_groups: 要监听的群名列表，None 表示监听所有
        """
        self._initialized = False
        self.listen_groups = (
            [g.strip() for g in listen_groups if g and g.strip()]
            if listen_groups else None
        )
        self._seen_messages: set = set()  # 已处理消息去重（保证每条只回复一次）
        self._session_snapshot: dict = {}  # 会话快照: {friend: "timestamp|last_content"}
        self._first_scan: bool = True  # 首次扫描标志，仅建立基线不拉消息
        self._my_name: str = ""  # 当前用户昵称，用于过滤自己发的消息
        self._sent_contents: set = set()  # 已发送消息内容集合，用于过滤自身消息

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
        """判断消息是否为自己发送的（发送者名称匹配 + 已发送内容匹配）"""
        s = sender.strip()
        if s == "你":
            return True
        if self._my_name:
            my = self._my_name.strip()
            if s == my or my in s:
                return True
        # 内容命中已发送记录（规范化比较，容忍空白差异）
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
                friend=target,
                messages=[message],
                close_weixin=False,
            )
            # 记录已发送内容，防止下次轮询把自己的回复当成新消息
            self._sent_contents.add(message.strip())
            logger.info(f"消息已发送到 '{target}': {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"发送消息到 '{target}' 失败: {e}")
            return False

    def send_message(self, who: str, message: str) -> bool:
        """发送消息（通用接口，群或好友均可）"""
        return self.send_group_message(who, message)

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

            # 首次扫描：建立快照基线，不拉取消息
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

            # 对比快照，检测有变化的会话
            changed_sessions = []
            for s in sessions:
                if not s or not s[0]:
                    continue
                friend = str(s[0]).strip()
                if not friend:
                    continue
                # 白名单过滤
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

            # 对有变化的会话拉取最近5条消息，构建结构化对话上下文
            messages = []
            for friend in changed_sessions:
                try:
                    msg_list = Messages.pull_messages(
                        friend=friend,
                        number=5,
                        close_weixin=False,
                    )
                    if not msg_list:
                        continue
                    # 解析所有消息，构建结构化对话历史
                    all_msgs = []
                    for msg_dict in msg_list:
                        msg = WeChatMessage.from_pyweixin(msg_dict, chat_name=friend)
                        if not msg.content.strip():
                            continue
                        all_msgs.append(msg)
                    # 找出最后一条未处理的新消息（非自己发的）
                    new_idx = -1
                    for i, msg in enumerate(all_msgs):
                        if self._is_self_message(msg.sender, msg.content):
                            continue
                        msg_key = (
                            f"{' '.join(msg.sender.strip().split())}|"
                            f"{' '.join(msg.content.strip().split())}|"
                            f"{msg.chat.strip()}"
                        )
                        if msg_key not in self._seen_messages:
                            self._seen_messages.add(msg_key)
                            new_idx = i
                    if len(self._seen_messages) > 1000:
                        for _ in range(200):
                            self._seen_messages.pop()
                    if new_idx >= 0:
                        new_msg = all_msgs[new_idx]
                        # 将新消息之前的所有消息构建为结构化对话历史
                        # （从聊天窗口实时拉取，非本地记录）
                        history = []
                        for i in range(new_idx):
                            msg = all_msgs[i]
                            is_self = self._is_self_message(msg.sender, msg.content)
                            role = "assistant" if is_self else "user"
                            history.append({"role": role, "content": msg.content})
                        new_msg.history = history
                        messages.append(new_msg)
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
