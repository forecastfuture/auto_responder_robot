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

已知限制:
    微信 4.1.8+ 客户端会忽略程序注入的右键点击（真实鼠标才能弹出消息右键菜单），
    pyweixin.pull_messages 依赖的右键'多选'菜单在该版本上无法打开。
    因此拉取消息改为 UIA 直读聊天区消息行：内容/类型来自消息行本身，
    发送人通过会话预览（'三月: xxx'）与已发送内容匹配解析，详见 _pull_messages_uia。
"""

import os
import re
import time
from typing import List, Optional, Any

from utils.set_logger import get_logger

logger = get_logger()

# 图片消息类型关键词
_IMAGE_TYPES = {"图片", "image", "[图片]", "[image]"}

# 图片保存目录（data/images/）
_IMAGE_SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "images")

# 时间戳等系统消息行的 UI 类名（不是真正的消息）
_SYSTEM_ROW_CLASS = "mmui::ChatItemView"

# 单次拉取最大尝试次数
_PULL_MAX_ATTEMPTS = 3


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
        self._pull_fail_cooldown: dict = {}  # {chat_name: expiry_timestamp} 拉取失败冷却，期间跳过该会话
        self._session_previews: dict = {}  # {chat_name: 会话预览文本('发送人: 内容')} 用于解析发送人
        self._sender_cache: dict = {}  # {(chat, content): sender} 群聊发送人缓存（由预览解析回填）

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

    def is_logged_in(self) -> bool:
        """检测微信客户端当前是否处于登录状态

        通过尝试打开主窗口判断：能定位到主界面(mmui::MainWindow)即已登录；
        处于登录窗口(mmui::LoginWindow)或微信未启动时均返回 False。

        Returns:
            True 表示微信已登录且可进行 UI 自动化操作
        """
        try:
            from pyweixin import Navigator

            Navigator.open_weixin(is_maximize=False)
            return True
        except Exception as e:
            logger.debug(f"微信登录状态检测: 未登录或不可用 ({self._format_ui_error(e)})")
            return False

    def _reset_session_state(self) -> None:
        """重新登录成功后重置会话缓存，重新建立消息基线

        清空会话快照/预览/发送人缓存等，并将 _first_scan 置为 True，
        使下一次扫描重新建立基线，避免把历史消息当成新消息重复回复。
        保留 _seen_messages 以防止对同一消息二次回复。
        """
        self._session_snapshot.clear()
        self._session_previews.clear()
        self._sender_cache.clear()
        self._recent_context.clear()
        self._pull_fail_cooldown.clear()
        self._first_scan = True

    def _is_login_window(self) -> bool:
        """检测微信当前是否停留在登录窗口（mmui::LoginWindow）"""
        try:
            from pywinauto import Desktop
            from pyweixin.Uielements import Login_window

            login_window = Desktop(backend="uia").window(**Login_window.LoginWindow)
            return bool(login_window.exists(timeout=1))
        except Exception as e:
            logger.debug(f"登录窗口检测异常: {self._format_ui_error(e)}")
            return False

    def _click_enter_weixin(self) -> bool:
        """在登录窗口点击'进入微信'按钮，用已记住的账号自动重登（无需扫码）

        微信 4.x 退出登录后停留在登录窗口，若账号被记住会显示'进入微信'按钮，
        点击即可免扫码重新登录。找不到按钮时返回 False，由调用方回退到扫码流程。
        """
        try:
            from pywinauto import Desktop
            from pyweixin.Uielements import Login_window

            login_window = Desktop(backend="uia").window(**Login_window.LoginWindow)
            if not login_window.exists(timeout=3):
                logger.warning("未找到微信登录窗口，无法自动点击'进入微信'")
                return False
            try:
                login_window.restore()
            except Exception:
                pass
            enter_btn = login_window.child_window(**Login_window.LoginButton)
            if not enter_btn.exists(timeout=2):
                logger.info("登录窗口未出现'进入微信'按钮，可能需要扫码登录")
                return False
            enter_btn.click_input()
            logger.info("已点击'进入微信'按钮，正在自动重新登录...")
            return True
        except Exception as e:
            logger.warning(f"点击'进入微信'按钮失败: {self._format_ui_error(e)}")
            return False

    def _wait_logged_in(self, timeout: int = 180, poll_interval: int = 3) -> bool:
        """轮询等待微信进入已登录状态，成功后重置会话缓存

        Returns:
            True 表示在超时前检测到已登录；False 表示超时或微信已退出
        """
        from pyweixin import Navigator
        from pyweixin.Errors import NotLoginError, NotStartError

        deadline = time.time() + max(0, int(timeout))
        while time.time() < deadline:
            time.sleep(poll_interval)
            try:
                Navigator.open_weixin(is_maximize=False)
                logger.info("检测到微信已登录，重新登录成功")
                self._reset_session_state()
                self._initialized = True
                return True
            except NotLoginError:
                continue
            except NotStartError:
                logger.error("微信已退出，重新登录中止")
                self._initialized = False
                return False
            except Exception:
                continue
        return False

    def logout(self, wait_seconds: int = 15) -> bool:
        """主动退出当前微信账号登录，使微信回到登录窗口

        通过 pyweixin Settings.Log_out 打开设置 → 点击'退出登录' → '确定'。
        退出后微信停留在登录窗口(mmui::LoginWindow)，可再用 relogin() 重新登录。

        Args:
            wait_seconds: 等待确认已进入登录窗口的最长秒数，默认 15

        Returns:
            True 表示已确认退出登录（处于登录窗口或未登录状态）
        """
        if not self.is_logged_in():
            logger.info("微信当前未登录，无需退出")
            self._initialized = False
            return True
        try:
            from pyweixin import Settings
        except ImportError:
            logger.error("pywechat 未安装，无法退出登录")
            return False

        try:
            logger.info("正在退出微信登录...")
            Settings.Log_out(is_maximize=False, close_weixin=False)
        except Exception as e:
            logger.error(f"退出登录操作失败: {self._format_ui_error(e)}")
            return False

        deadline = time.time() + max(0, int(wait_seconds))
        while time.time() < deadline:
            time.sleep(1)
            if self._is_login_window():
                self._initialized = False
                logger.info("微信已退出登录，当前停留在登录窗口")
                return True

        if self.is_logged_in():
            logger.error("退出登录后仍处于已登录状态，退出可能未生效")
            return False
        self._initialized = False
        logger.info("微信已退出登录")
        return True

    def relogin(self, wait_seconds: int = 180, full_logout: bool = False) -> bool:
        """重新登录 / 刷新微信连接（供每日定时任务调用）

        防止机器人长时间运行后因连接超时、微信掉线而失效。

        Args:
            wait_seconds: 掉线后等待登录成功的最长秒数，默认 180
            full_logout: 为 True 时先主动退出登录再重新登录（完整验证退出/重登流程）；
                         为 False 时仅在已登录状态下刷新连接（保持在线，防止超时退出）。

        流程:
            1. full_logout=True 且当前已登录 → 先 logout() 退出到登录窗口；
            2. 确认微信进程在运行，未运行则尝试启动；
            3. 检测登录状态:
               - 已登录: 刷新自动化连接并重置会话缓存；
               - 未登录(登录窗口): 先尝试点击'进入微信'自动重登，
                 失败则保存登录二维码到 data/images/login_qrcode.png 并轮询等待扫码。

        Returns:
            True 表示操作结束后微信处于登录状态
        """
        try:
            from pyweixin import Navigator, Tools
            from pyweixin.Errors import NotLoginError, NotStartError
        except ImportError:
            logger.error("pywechat 未安装，无法重新登录微信")
            return False

        # 0. 需要完整退出/重登时，先主动退出登录
        if full_logout:
            logger.info("full_logout=True，先主动退出登录再重新登录")
            self.logout()

        # 1. 确保微信进程在运行
        try:
            if not Tools.is_weixin_running():
                logger.warning("微信进程未运行，尝试启动微信...")
                exe_path = Tools.where_weixin()
                if exe_path:
                    os.startfile(exe_path)
                    time.sleep(8)
        except Exception as e:
            logger.warning(f"检查/启动微信进程失败: {e}")

        # 2. 已登录 → 刷新连接并重置会话缓存
        try:
            Navigator.open_weixin(is_maximize=False)
            logger.info("微信已处于登录状态，刷新连接并重置会话缓存")
            self._reset_session_state()
            self._initialized = True
            return True
        except NotLoginError:
            logger.warning("微信当前未登录，尝试重新登录...")
        except NotStartError:
            logger.error("微信未启动，无法重新登录")
            self._initialized = False
            return False
        except Exception as e:
            logger.warning(f"登录状态检测异常，按未登录处理: {self._format_ui_error(e)}")

        # 3. 未登录 → 优先点击'进入微信'自动重登（记住的账号无需扫码）
        if self._click_enter_weixin():
            if self._wait_logged_in(timeout=min(30, max(5, wait_seconds))):
                return True
            logger.warning("点击'进入微信'后仍未登录，回退到扫码登录")

        # 4. 回退：保存二维码并轮询等待扫码登录
        qr_path = os.path.join(_IMAGE_SAVE_DIR, "login_qrcode.png")
        try:
            os.makedirs(_IMAGE_SAVE_DIR, exist_ok=True)
            Tools.capture_Login_QRCode(qr_path)
            logger.info(
                f"已保存微信登录二维码: {qr_path}，请在 {wait_seconds} 秒内扫码登录"
            )
        except Exception as e:
            logger.error(f"获取登录二维码失败: {e}")

        if self._wait_logged_in(timeout=wait_seconds):
            return True

        logger.error("等待登录超时，微信仍未登录")
        self._initialized = False
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
            self._recover_wechat_ui_state(3)
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

    def _ensure_wechat_foreground(self, main_window=None) -> None:
        """尽力把微信主窗口带到前台（ALT 技巧绕过 SetForegroundWindow 限制）

        UIA 读取本身不依赖前台，但键盘输入（ESC 清理等）只作用于前台窗口。
        """
        try:
            import win32api
            import win32con
            import win32gui

            if main_window is None:
                return
            try:
                main_window.set_focus()
                time.sleep(0.15)
            except Exception:
                pass
            try:
                if win32gui.GetForegroundWindow() != main_window.handle:
                    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                    try:
                        win32gui.SetForegroundWindow(main_window.handle)
                    finally:
                        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
                    time.sleep(0.15)
            except Exception:
                pass
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"激活微信窗口失败(可忽略): {e}")

    def _recover_wechat_ui_state(self, esc_count: int = 3) -> None:
        """拉取失败后的 UI 自愈：发送多次 ESC 清理残留状态"""
        count = max(1, int(esc_count))
        try:
            from pywinauto.keyboard import send_keys
            for _ in range(count):
                send_keys('{ESC}')
                time.sleep(0.2)
            logger.info(f"微信 UI 状态恢复完成（已发送 {count} 次 ESC）")
        except Exception as e:
            logger.debug(f"UI 状态恢复失败(可忽略): {e}")

    def _is_multiselect_active(self) -> bool:
        """检测聊天区是否残留'多选'模式（存在 CheckBox 即处于多选状态）"""
        if not self._initialized:
            return False
        try:
            from pyweixin import GlobalConfig, Navigator
            from pyweixin.Uielements import Lists

            main_window = Navigator.open_weixin(is_maximize=GlobalConfig.is_maximize)
            chat_list = main_window.child_window(**Lists.FriendChatList)
            return bool(chat_list.children(control_type="CheckBox"))
        except Exception:
            return False

    @staticmethod
    def _parse_preview_sender(preview: str):
        """解析会话预览 '三月: 下午好' -> ('三月', '下午好'); 无前缀返回 (None, None)"""
        text = (preview or "").strip()
        if not text:
            return None, None
        m = re.match(r"^([^:：\n]{1,30})[:：]\s*(.+)$", text, re.S)
        if not m:
            return None, None
        return m.group(1).strip(), m.group(2).strip()

    @staticmethod
    def _preview_matches(preview_content: str, content: str) -> bool:
        """会话预览内容与消息行内容匹配（兼容预览被截断为省略号的情况）"""
        a = " ".join((preview_content or "").split()).rstrip(".…")
        b = " ".join((content or "").split())
        if not a or not b:
            return False
        if a == b:
            return True
        return len(a) >= 4 and (b.startswith(a) or a.startswith(b))

    def _resolve_sender(self, chat: str, content: str, is_group: bool, friend: str,
                        preview_sender: Optional[str] = None) -> str:
        """确定消息发送人

        优先级: 已发送内容匹配(自己) > 会话预览('你'/群成员名) > 发送人缓存 > 私聊好友名 > '群成员'
        群聊中由预览解析出的发送人会写入缓存，同内容的历史行可直接复用。
        """
        if self._is_self_message("", content):
            return self._my_name or "你"
        if preview_sender == "你":
            return self._my_name or "你"
        norm = " ".join(content.split())
        if preview_sender:
            if is_group:
                key = (chat, norm)
                if key not in self._sender_cache:
                    self._sender_cache[key] = preview_sender
                    if len(self._sender_cache) > 500:
                        self._sender_cache.pop(next(iter(self._sender_cache)))
                return preview_sender
            return friend
        cached = self._sender_cache.get((chat, norm))
        if cached:
            return cached
        if not is_group:
            return friend
        return "群成员"

    @staticmethod
    def _row_to_type(class_name: str, content: str) -> str:
        """按消息行 UI 类名与前后缀推断消息类型（与库 parse_messages 规则一致）"""
        try:
            from pyweixin.Uielements import Special_Labels
            L = Special_Labels
            image_label, video_label, file_label = L.Image, L.Video, L.File
            link_label, miniprogram_label = L.Link, L.MiniProgram
            channels_label, redpacket_label = L.Channels, L.RedPacket
            transfer_label, chat_history_label = L.Transfer, L.ChatHistory
            voiceCall_label, videoCall_label = L.VoiceCall, L.VideoCall
            emoji_label = L.Emoji
        except Exception:
            image_label, video_label, file_label = "[图片]", "[视频]", "[文件]"
            link_label, miniprogram_label = "[链接]", "[小程序]"
            channels_label, redpacket_label = "[视频号]", "[微信红包]"
            transfer_label, chat_history_label = "[微信转账]", "[聊天记录]"
            voiceCall_label, videoCall_label, emoji_label = "[语音通话]", "[视频通话]", "[动画表情]"

        if class_name == "mmui::ChatPersonalCardItemView":
            return "好友名片"
        if class_name == "mmui::ChatBubbleReferItemView":
            if content.startswith(image_label):
                return "图片"
            if content.startswith(video_label):
                return "视频"
            if content.startswith(emoji_label):
                return "动画表情"
            return "文本"
        if class_name == "mmui::ChatBubbleItemView":
            if content.startswith(file_label):
                return "文件"
            if content.startswith(link_label):
                return "链接"
            if content.startswith(miniprogram_label):
                return "小程序"
            if content.startswith(channels_label):
                return "视频号"
            if content.endswith(redpacket_label):
                return "微信红包"
            if content.endswith(transfer_label):
                return "微信转账"
            if content.startswith(chat_history_label):
                return "聊天记录"
            if content.startswith(voiceCall_label):
                return "语音通话"
            if content.startswith(videoCall_label):
                return "视频通话"
            return "文本"
        return "文本"

    @staticmethod
    def _dismiss_ui_popups():
        """尝试按Escape关闭微信中残留的UI弹窗/菜单（如'多选'菜单）"""
        try:
            from pywinauto.keyboard import send_keys
            send_keys('{ESC}')
            logger.info("已发送ESC键尝试关闭残留UI弹窗")
        except Exception as e:
            logger.debug(f"发送ESC键失败(可忽略): {e}")

    def _pull_messages_uia(self, friend: str, number: int = 5) -> list:
        """直接读取聊天区可见消息行（不依赖右键菜单）

        微信 4.1.8+ 忽略程序注入的右键点击，pyweixin 的 pull_messages 依赖
        右键'多选'菜单，在该版本上必然失败。此方法改为纯 UIA 读取：
            - 消息行的 class_name/window_text 直接给出内容与类型；
            - 发送人通过 会话预览('三月: xxx') + 已发送内容匹配 解析，
              私聊非自己即好友，群聊未识别的发送人记为'群成员'。

        Returns:
            [{'消息发送人','消息内容','消息类型'}...] 最新在前（与库 pull_messages 一致）
        """
        from pyweixin import Navigator, Tools
        from pyweixin.Uielements import Lists

        main_window = Navigator.open_dialog_window(friend=friend)
        self._ensure_wechat_foreground(main_window)
        chat_list = main_window.child_window(**Lists.FriendChatList)
        rows = chat_list.children(control_type="ListItem")

        try:
            is_group = Tools.is_group_chat(main_window)
        except Exception:
            is_group = False

        preview = self._session_previews.get(friend, "")
        preview_sender, preview_content = self._parse_preview_sender(preview)

        # [(class_name, content)] 按时间正序, 跳过时间戳等系统行
        items = []
        for row in rows:
            try:
                cls = row.class_name() or ""
                text = (row.window_text() or "").strip()
            except Exception:
                continue
            if cls == _SYSTEM_ROW_CLASS:
                continue
            items.append((cls, text))
        if number > 0:
            items = items[-number:]

        # 定位与预览匹配的行（取最后一条匹配，预览对应会话最新一条消息）
        match_idx = None
        for idx, (_, text) in enumerate(items):
            if self._preview_matches(preview_content or "", text or "[图片]"):
                match_idx = idx

        details = []
        for idx, (cls, text) in enumerate(items):
            content = text or "[图片]"  # 图片等无文本行
            msg_type = self._row_to_type(cls, content)
            use_preview = match_idx is not None and idx == match_idx and preview_sender
            sender = self._resolve_sender(
                friend, content, is_group, friend,
                preview_sender if use_preview else None,
            )
            details.append({"消息发送人": sender, "消息内容": content, "消息类型": msg_type})

        details.reverse()  # 最新在前
        return details

    def _pull_messages_safe(self, friend: str, number: int = 5) -> list:
        """带重试与 UI 自愈的拉取封装（最多 _PULL_MAX_ATTEMPTS 次）

        每次失败后发送 ESC 清理残留状态并重试；全部失败返回空列表，
        由调用方设置冷却期跳过该会话。
        """
        last_err: Optional[Exception] = None
        for attempt in range(1, _PULL_MAX_ATTEMPTS + 1):
            try:
                msg_list = self._pull_messages_uia(friend, number=number)
                if attempt > 1:
                    logger.info(f"第 {attempt} 次拉取 '{friend}' 消息成功")
                return msg_list or []
            except Exception as e:
                last_err = e
                err_desc = self._format_ui_error(e)
                suffix = "，恢复微信 UI 状态后重试" if attempt < _PULL_MAX_ATTEMPTS else ""
                logger.warning(f"拉取 '{friend}' 消息第 {attempt} 次失败({err_desc}){suffix}")
                if attempt < _PULL_MAX_ATTEMPTS:
                    self._recover_wechat_ui_state(esc_count=3 * attempt)
                    time.sleep(0.5)
        logger.error(
            f"拉取 '{friend}' 消息 {_PULL_MAX_ATTEMPTS} 次均失败("
            f"{self._format_ui_error(last_err)})，跳过该会话本轮消息"
        )
        return []

    @staticmethod
    def _format_ui_error(exc: Exception) -> str:
        """格式化 pywinauto 异常，避免直接打印巨大的元素字典"""
        exc_str = str(exc)
        # pywinauto 异常常以 dict 形式输出，提取关键信息
        if "'title':" in exc_str:
            import re
            title_match = re.search(r"'title':\s*'([^']*)'", exc_str)
            ctrl_match = re.search(r"'control_type':\s*'([^']*)'", exc_str)
            title = title_match.group(1) if title_match else "未知"
            ctrl = ctrl_match.group(1) if ctrl_match else "未知"
            return f"UI元素异常(title={title}, type={ctrl})"
        # 截断过长的异常文本
        return exc_str[:200] if len(exc_str) > 200 else exc_str

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
            msg_list = self._pull_messages_safe(chat_name, number=count)
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
                        self._session_previews[friend] = content
                self._first_scan = False
                logger.info(f"首次扫描完成，建立 {len(self._session_snapshot)} 个会话基线")
                return []

            changed_sessions = []
            now_ts = time.time()
            for s in sessions:
                if not s or not s[0]:
                    continue
                friend = str(s[0]).strip()
                if not friend:
                    continue
                if self.listen_groups and friend not in self.listen_groups:
                    continue
                # 跳过冷却中的会话（拉取失败后60秒内不再重试）
                cooldown = self._pull_fail_cooldown.get(friend)
                if cooldown and now_ts < cooldown:
                    logger.debug(f"会话 '{friend}' 在冷却中，跳过本轮")
                    continue
                ts = s[1] if len(s) > 1 else ""
                content = s[2] if len(s) > 2 else ""
                self._session_previews[friend] = content
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
                    msg_list = self._pull_messages_safe(friend, number=5)
                    if not msg_list:
                        # 拉取失败，设置60秒冷却避免反复重试同一会话
                        self._pull_fail_cooldown[friend] = time.time() + 60
                        logger.info(f"会话 '{friend}' 进入60秒冷却期")
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

                    # 筛选新消息：标记所有新消息为已见，但只返回最后一条新消息
                    # 这样同一会话连续收到多条消息时，不会逐条回复，只回复最新的
                    last_new_msg = None
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
                        last_new_msg = msg
                    if last_new_msg:
                        messages.append(last_new_msg)
                except Exception as e:
                    err_desc = self._format_ui_error(e)
                    logger.error(f"处理 '{friend}' 的消息失败: {err_desc}")
                    self._pull_fail_cooldown[friend] = time.time() + 60

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
