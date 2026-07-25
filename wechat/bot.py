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
        self.listen_groups = listen_groups
        self._seen_messages: set = set()  # 已处理消息去重

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

    def send_group_message(self, group_name: str, message: str) -> bool:
        """
        发送消息到群（或好友）

        Args:
            group_name: 群名或好友备注
            message: 消息内容

        Returns:
            是否发送成功
        """
        if not self._initialized:
            logger.error("微信未初始化，无法发送消息")
            return False

        try:
            from pyweixin import Messages

            Messages.send_messages_to_friend(
                friend=group_name,
                messages=[message],
                close_weixin=False,
            )
            logger.info(f"消息已发送到 '{group_name}': {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"发送消息到 '{group_name}' 失败: {e}")
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

        通过 Messages.check_new_messages() 扫描会话列表中的新消息，
        然后过滤出目标群的消息并进行去重。

        注意: 该方法会进行 UI 自动化操作（打开微信窗口、扫描会话列表），
        调用频率不宜过高，建议间隔 10-15 秒。

        Returns:
            WeChatMessage 列表
        """
        if not self._initialized:
            return []

        try:
            from pyweixin import Messages

            new_messages_raw = Messages.check_new_messages(close_weixin=False)
            messages = []

            for friend, msg_list in new_messages_raw.items():
                # 群过滤：只处理目标群
                if self.listen_groups and friend not in self.listen_groups:
                    continue

                for msg_dict in msg_list:
                    msg = WeChatMessage.from_pyweixin(msg_dict, chat_name=friend)

                    # 只处理文本消息（pyweixin 消息类型为中文）
                    if msg.msg_type and msg.msg_type not in ("text", "文本", "Text"):
                        continue

                    # 跳过空消息
                    if not msg.content or not msg.content.strip():
                        continue

                    # 去重
                    msg_key = f"{msg.sender}|{msg.content}|{msg.chat}"
                    if msg_key in self._seen_messages:
                        continue
                    self._seen_messages.add(msg_key)

                    # 限制去重集合大小
                    if len(self._seen_messages) > 500:
                        self._seen_messages.clear()
                        self._seen_messages.add(msg_key)

                    messages.append(msg)

            return messages
        except Exception as e:
            logger.error(f"获取消息失败: {e}")
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
