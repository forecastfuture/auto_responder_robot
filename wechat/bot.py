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

import time
from typing import List, Optional, Any

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
        self._seen_messages: dict = {}  # 已处理消息去重（保证每条只回复一次），dict 保持插入顺序便于 FIFO 淘汰
        self._session_snapshot: dict = {}  # 会话快照: {friend: "timestamp|last_content"}
        self._first_scan: bool = True  # 首次扫描标志，仅建立基线不拉消息
        self._my_name: str = ""  # 当前用户昵称，记录自己是谁
        self._sent_contents: set = set()  # 已发送/回复消息内容集合
        self._sent_contents_ordered: list = []  # 保持插入顺序，用于淘汰旧记录

    def init_wechat(self) -> bool:
        """初始化微信连接，验证客户端已运行并登录"""
        try:
            from pyweixin import Tools, GlobalConfig

            GlobalConfig.close_weixin = False
            GlobalConfig.is_maximize = False
            # search_pages 设为非零值，优先在会话列表中按 automation_id 精确查找好友/群聊，
            # 避免使用顶部搜索栏时搜索结果命中同名公众号/服务号（class_name 均为 mmui::SearchContentCellView）
            GlobalConfig.search_pages = 5

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
        # 策略1: 发送者是自己
        if s == "你":
            return True
        if self._my_name:
            my = self._my_name.strip()
            if s == my or my in s:
                return True
        # 策略2: 内容命中已回复记录（规范化比较，容忍空白差异）
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
            content = message.strip()
            self._sent_contents.add(content)
            self._sent_contents_ordered.append(content)
            # 限制集合大小，淘汰最早的记录
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

    def _recover_to_session_view(self) -> None:
        """恢复 UI 到会话列表视图

        pull_messages 失败后 UI 可能停留在聊天窗口视图（而非会话列表），
        导致后续 dump_sessions 找不到会话列表元素。
        此方法显式点击侧边栏"微信"按钮，确保切回会话列表视图。
        """
        try:
            from pyweixin import Navigator, GlobalConfig
            from pyweixin.Uielements import SideBar

            main_window = Navigator.open_weixin(is_maximize=GlobalConfig.is_maximize)
            sidebar_btn = main_window.child_window(**SideBar.Weixin)
            if sidebar_btn.exists(timeout=1):
                sidebar_btn.click_input()
                time.sleep(2)
                logger.info("已恢复到会话列表视图")
        except Exception as e:
            logger.warning(f"恢复会话列表视图失败: {e}")

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
            from pyweixin import Messages, Navigator, GlobalConfig
            from pyweixin.Uielements import SideBar, Main_window

            # dump_sessions 内部点击侧边栏后立即访问会话列表，
            # 若 UI 未渲染完毕会抛 ElementNotFoundError，需重试
            # 拉取消息失败后 UI 可能停留在聊天窗口视图，也需恢复
            max_retries = 5
            sessions = None
            for attempt in range(max_retries):
                try:
                    sessions = Messages.dump_sessions(chat_only=True, close_weixin=False)
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"dump_sessions 第 {attempt + 1} 次失败，尝试恢复 UI 状态后重试: {e}"
                        )
                        # 显式点击侧边栏"微信"按钮，确保主界面处于会话列表视图
                        self._recover_to_session_view()
                    else:
                        logger.error(f"dump_sessions 重试 {max_retries} 次后仍失败，跳过本轮: {e}")
                        return []

            # dump_sessions 全部重试失败
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

            # 对有变化的会话拉取最近消息
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
                    for msg_dict in msg_list:
                        msg = WeChatMessage.from_pyweixin(msg_dict, chat_name=friend)
                        if not msg.content.strip():
                            continue
                        # 跳过自己发的消息
                        if self._is_self_message(msg.sender, msg.content):
                            continue
                        # 去重：保证每条消息只处理一次
                        msg_key = (
                            f"{' '.join(msg.sender.strip().split())}|"
                            f"{' '.join(msg.content.strip().split())}|"
                            f"{msg.chat.strip()}"
                        )
                        if msg_key in self._seen_messages:
                            continue
                        self._seen_messages[msg_key] = True
                        while len(self._seen_messages) > 1000:
                            # FIFO 淘汰最旧的消息键
                            oldest = next(iter(self._seen_messages))
                            del self._seen_messages[oldest]
                        messages.append(msg)
                except Exception as e:
                    logger.error(f"拉取 '{friend}' 的消息失败: {e}")
                    # pull_messages 失败后 UI 可能停留在聊天窗口视图（如"只有系统消息"异常），
                    # 必须恢复到会话列表视图，否则后续 dump_sessions 会失败
                    self._recover_to_session_view()

            if messages:
                logger.info(f"共获取 {len(messages)} 条新消息")
            return messages

        except Exception as e:
            logger.error(f"获取消息失败: {e}", exc_info=True)
            # 兜底恢复 UI 状态
            self._recover_to_session_view()
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
