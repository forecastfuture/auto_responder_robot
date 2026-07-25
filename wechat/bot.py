"""微信机器人 - 基于 pywechat (pyweixin 模块) 的微信 PC 客户端自动化

pywechat 通过 pywinauto 自动化 Windows 微信客户端实现消息收发。
使用前需要:
    1. Windows 系统上运行微信 PC 客户端（版本 4.1.x）
    2. pip install pywechat127  # pip install pywechat127 --user --no-cache-dir
    3. 微信客户端保持登录状态

主要功能:
    - 发送消息到群/好友
    - 监听群消息（通过轮询会话列表新消息）
    - 获取会话列表
"""

import logging
import re
import time
from typing import List, Optional, Any

logger = logging.getLogger(__name__)


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
        self.sender = sender  # 发送者昵称
        self.content = content  # 消息内容
        self.chat = chat  # 聊天窗口名（群名或好友昵称）
        self.msg_type = msg_type  # 消息类型: text, image, file, etc.
        self.raw = raw  # 原始消息对象

    def __repr__(self):
        return (
            f"WeChatMessage(sender='{self.sender}', chat='{self.chat}', "
            f"content='{self.content[:30]}...')"
        )

    @classmethod
    def from_pyweixin(cls, msg_dict: dict, chat_name: str = "") -> "WeChatMessage":
        """
        从 pyweixin 消息字典转换为 WeChatMessage

        pyweixin 的 pull_messages / check_new_messages 返回格式:
            {'消息发送人': str, '消息内容': str, '消息类型': str}
        """
        sender = str(msg_dict.get("消息发送人", "")) if msg_dict.get("消息发送人") else ""
        content = str(msg_dict.get("消息内容", "")) if msg_dict.get("消息内容") else ""
        msg_type = str(msg_dict.get("消息类型", "text")) if msg_dict.get("消息类型") else "text"
        return cls(
            sender=sender,
            content=content,
            chat=chat_name,
            msg_type=msg_type,
            raw=msg_dict,
        )


class WeChatBot:
    """微信机器人 - pyweixin 封装

    基于 pywechat127 包的 pyweixin 模块，适配微信 4.1.x 客户端。
    所有 UI 自动化操作均通过 pywinauto 实现，不涉及逆向 Hook。
    """

    def __init__(self, listen_groups: Optional[List[str]] = None):
        """
        初始化微信机器人

        Args:
            listen_groups: 要监听的群名列表，None 表示监听所有
        """
        self._initialized = False
        # 监听白名单（去除首尾空格，确保与回复目标一致）
        self.listen_groups = (
            [g.strip() for g in listen_groups if g and g.strip()]
            if listen_groups else None
        )
        self._seen_messages: set = set()  # 已处理消息去重
        self._session_snapshot: dict = {}  # 会话快照: {friend: "timestamp|last_content"}
        self._first_scan: bool = True  # 首次扫描标志，仅建立基线不拉消息
        self._my_name: str = ""  # 当前用户昵称，用于过滤自己发的消息
        self._sent_contents: set = set()  # 已发送消息内容集合，用于过滤自身消息
        self._sent_contents_ordered: list = []  # 保持插入顺序，用于淘汰旧记录

    def init_wechat(self) -> bool:
        """
        初始化微信连接

        通过 Tools.about_weixin() 验证微信 PC 客户端已运行并登录。

        Returns:
            是否初始化成功
        """
        try:
            from pyweixin import Tools, GlobalConfig

            # 全局配置：不关闭微信主窗口，便于持续运行
            GlobalConfig.close_weixin = False
            GlobalConfig.is_maximize = False
            # search_pages=0 表示从顶部搜索栏搜索好友，更快
            GlobalConfig.search_pages = 0

            info = Tools.about_weixin()
            self._initialized = True
            logger.info(f"微信连接成功: {info}")

            # 获取当前用户昵称，用于过滤自己发的消息
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
            logger.error(
                "请确保:\n"
                "1. Windows 微信 PC 客户端正在运行\n"
                "2. 微信已登录\n"
                "3. 微信窗口没有被最小化到托盘"
            )
            return False

    def _record_sent_message(self, message: str):
        """
        记录已发送的消息内容，用于后续过滤自身消息

        Args:
            message: 已发送的消息内容
        """
        content = message.strip()
        if not content:
            return
        self._sent_contents.add(content)
        self._sent_contents_ordered.append(content)
        # 限制集合大小，淘汰最早的记录
        while len(self._sent_contents_ordered) > 200:
            old = self._sent_contents_ordered.pop(0)
            self._sent_contents.discard(old)

    @staticmethod
    def _normalize(text: str) -> str:
        """规范化文本：去除首尾空白，合并连续空白为单个空格"""
        return re.sub(r"\s+", " ", text.strip())

    def _is_self_message(self, sender: str, content: str) -> bool:
        """
        判断消息是否为自己发送的（多层防御）

        判断策略:
            1. 发送者名称匹配（昵称 / "你" / 包含关系）
            2. 消息内容命中已发送记录（规范化后模糊匹配，最可靠）

        Args:
            sender: 消息发送者名称
            content: 消息内容

        Returns:
            是否为自己发送的消息
        """
        # --- 策略1: 发送者名称匹配 ---
        sender_stripped = sender.strip()
        if sender_stripped:
            # 微信 UI 中自己发的消息可能显示为 "你"
            if sender_stripped == "你":
                return True
            if self._my_name:
                my_name = self._my_name.strip()
                # 精确匹配或包含匹配（群昵称可能是 "昵称-备注" 格式）
                if sender_stripped == my_name or my_name in sender_stripped:
                    return True

        # --- 策略2: 内容命中已发送记录（规范化后比较，容忍空白差异） ---
        content_norm = self._normalize(content)
        if content_norm:
            for sent in self._sent_contents:
                if self._normalize(sent) == content_norm:
                    return True

        return False

    def _is_self_snapshot_content(self, last_content: str) -> bool:
        """
        判断会话列表中的最后一条消息内容是否为自己发送的

        会话列表内容格式：
            - 私聊: "消息内容"
            - 群聊: "发送人: 消息内容"
            - 可能带有 "[草稿]" 前缀

        Args:
            last_content: 会话列表中的最后一条消息内容

        Returns:
            是否为自己发送的消息
        """
        if not self._sent_contents:
            return False

        content = last_content.strip()
        # 去掉 "[草稿]" 前缀
        if content.startswith("[草稿]"):
            content = content[len("[草稿]"):].strip()

        content_norm = self._normalize(content)

        # 直接匹配（私聊格式，规范化后比较）
        for sent in self._sent_contents:
            if self._normalize(sent) == content_norm:
                return True

        # 群聊格式: "发送人: 消息内容"，去掉发送人前缀后再匹配
        if ": " in content:
            prefix, body = content.split(": ", 1)
            body_norm = self._normalize(body)
            if body_norm:
                for sent in self._sent_contents:
                    if self._normalize(sent) == body_norm:
                        # 进一步确认前缀是自己（避免误伤别人发的相同内容）
                        if self._my_name and (
                            prefix.strip() == self._my_name.strip()
                            or self._my_name.strip() in prefix.strip()
                        ):
                            return True
                        # 前缀为 "你" 即认为自己的
                        if prefix.strip() == "你":
                            return True

        return False

    def send_group_message(self, group_name: str, message: str) -> bool:
        """
        发送消息到群（或好友）

        Args:
            group_name: 群名或好友备注（必须与微信会话列表显示名称一致）
            message: 消息内容

        Returns:
            是否发送成功
        """
        if not self._initialized:
            logger.error("微信未初始化，无法发送消息")
            return False

        target = group_name.strip()
        if not target:
            logger.error("发送目标为空，拒绝发送")
            return False

        # 安全校验：如果配置了监听白名单，只允许向白名单内的会话发送
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
            self._record_sent_message(message)
            logger.info(f"消息已发送到 '{target}': {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"发送消息到 '{target}' 失败: {e}")
            return False

    def send_message(self, who: str, message: str) -> bool:
        """
        发送消息（通用接口，群或好友均可）

        Args:
            who: 群名或好友昵称
            message: 消息内容

        Returns:
            是否发送成功
        """
        return self.send_group_message(who, message)

    def get_messages(self) -> List[WeChatMessage]:
        """
        获取新消息列表

        通过会话列表快照对比检测新消息：
        1. 使用 dump_sessions(chat_only=True) 获取当前有消息的会话列表
        2. 对比上次快照，检测最后一条消息内容是否变化
        3. 对有变化的会话调用 pull_messages 拉取最近消息
        4. 去重后返回

        相比 check_new_messages（依赖红色未读标记），快照对比方式更可靠，
        不会因为机器人自身的 UI 操作清除了未读标记而漏检。

        注意: 该方法会进行 UI 自动化操作（打开微信窗口、扫描会话列表），
        调用频率不宜过高，建议间隔 10-15 秒。

        Returns:
            WeChatMessage 列表
        """
        if not self._initialized:
            return []

        try:
            from pyweixin import Messages

            # 获取当前会话列表（只有有消息的会话）
            sessions = Messages.dump_sessions(chat_only=True, close_weixin=False)
            if not sessions:
                logger.debug("会话列表为空，无消息可检测")
                return []

            # 首次扫描：建立快照基线，不拉取消息（避免返回旧消息）
            if self._first_scan:
                for s in sessions:
                    if not s or not s[0]:
                        continue
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
                ts = s[1] if len(s) > 1 else ""
                content = s[2] if len(s) > 2 else ""
                current_sig = f"{ts}|{content}"

                # 白名单过滤：只处理目标会话，其他会话一律不拉取不回复
                if self.listen_groups and friend not in self.listen_groups:
                    continue

                prev_sig = self._session_snapshot.get(friend)
                if prev_sig is None:
                    # 新会话（之前快照中没有），视为有变化
                    changed_sessions.append(friend)
                elif current_sig != prev_sig:
                    # 最后消息内容或时间变化，有新消息
                    changed_sessions.append(friend)

                # 更新快照（无论是否变化都更新，保持最新状态）
                self._session_snapshot[friend] = current_sig

            if not changed_sessions:
                logger.debug("所有会话无新消息变化")
                return []

            # 预过滤：如果会话最后一条消息是自己发的，跳过该会话
            # （避免机器人回复后触发下一轮拉取，把自己的回复当新消息）
            snapshot_content_map = {}
            for s in sessions:
                if s and s[0]:
                    snapshot_content_map[s[0]] = s[2] if len(s) > 2 else ""

            filtered_sessions = []
            for friend in changed_sessions:
                last_content = str(snapshot_content_map.get(friend, "")).strip()
                # 使用 _is_self_snapshot_content 处理群聊 "发送人: 内容" 前缀格式
                if last_content and self._is_self_snapshot_content(last_content):
                    logger.debug(f"'{friend}' 最后一条是自己发的消息，跳过")
                    continue
                filtered_sessions.append(friend)

            if not filtered_sessions:
                logger.debug("变化的会话均为自身消息触发，无需处理")
                return []

            logger.info(f"检测到 {len(filtered_sessions)} 个会话有新消息: {filtered_sessions}")

            # 对有变化的会话拉取最近消息
            messages = []
            pull_count = 5  # 拉取最近5条消息，通过去重过滤已处理的
            for friend in filtered_sessions:
                try:
                    msg_list = Messages.pull_messages(
                        friend=friend,
                        number=pull_count,
                        close_weixin=False,
                    )
                    if not msg_list:
                        logger.debug(f"'{friend}' 拉取到 0 条消息")
                        continue

                    for msg_dict in msg_list:
                        msg = WeChatMessage.from_pyweixin(msg_dict, chat_name=friend)

                        # 跳过空消息
                        if not msg.content or not msg.content.strip():
                            continue

                        # 跳过自己发的消息（多层防御：名称匹配 + 已发送内容匹配）
                        if self._is_self_message(msg.sender, msg.content):
                            logger.debug(f"跳过自身消息: {msg}")
                            continue

                        # 去重（规范化键：容忍 UI 自动化读取的空白差异）
                        msg_key = (
                            f"{self._normalize(msg.sender)}|"
                            f"{self._normalize(msg.content)}|"
                            f"{msg.chat.strip()}"
                        )
                        if msg_key in self._seen_messages:
                            continue
                        self._seen_messages.add(msg_key)

                        # 限制去重集合大小（渐进淘汰，避免清空后旧消息重复返回）
                        if len(self._seen_messages) > 1000:
                            for _ in range(200):
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
        """
        获取当前所有聊天窗口名称

        通过 Messages.dump_sessions() 获取会话列表。

        Returns:
            聊天名称列表
        """
        if not self._initialized:
            return []

        try:
            from pyweixin import Messages

            sessions = Messages.dump_sessions(close_weixin=False)
            if sessions:
                # sessions 格式: [('发送人', '最后聊天时间', '最后聊天内容'), ...]
                return [s[0] for s in sessions if s and s[0]]
            return []
        except Exception as e:
            logger.error(f"获取聊天列表失败: {e}")
            return []

    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized
