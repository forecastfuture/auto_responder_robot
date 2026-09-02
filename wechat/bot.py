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
import time
from typing import List, Optional, Any

from utils.set_logger import get_logger

logger = get_logger()

# 图片消息类型关键词
_IMAGE_TYPES = {"图片", "image", "[图片]", "[image]"}

# 图片保存目录（data/images/）
_IMAGE_SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "images")

# pyweixin select_chatList 补丁安装标记
_PYWEIXIN_PATCHED = False


def _robust_select_chatlist(main_window):
    """稳健版 Tools.select_chatList（运行时替换 pyweixin 内部实现）

    原实现的问题（导致拉取消息持续报 title=多选, type=MenuItem）:
        1. 右键位置硬编码 (left+120, bottom-60) 及回退 (right-120, bottom-60):
           - 矮消息（如单行文本 h≈56px）时 bottom-60 会越过消息上沿，
             右键落在上方的时间戳系统消息上，弹不出"多选"菜单
           - 自己发的消息（气泡靠右）时 left+120 落在空白区域
        2. 聊天区残留多选模式时，右键菜单不含"多选"项，直接抛异常

    修复策略:
        - 已处于多选模式时直接返回最后的 CheckBox（兼容残留状态）
        - 优先右键消息子元素（气泡/图片）中心，坐标永不落空
        - 依次尝试多个候选位置，每次失败先 ESC 关掉错误菜单再换位置

    Args:
        main_window: 微信主窗口 WindowSpecification

    Returns:
        最后一个 CheckBox 元素（同原实现），无可选消息时返回 None

    Raises:
        RuntimeError: 所有候选位置均未能打开"多选"菜单
    """
    from pyweixin.Uielements import Lists, MenuItems
    from pywinauto import mouse

    main_window.restore()
    chat_list = main_window.child_window(**Lists.FriendChatList)
    if not chat_list.exists(timeout=0.2):
        print("非正常好友,无法选中消息!")
        return None

    # 激活消息列表并跳到底部（与原实现一致）
    rect = chat_list.rectangle()
    mouse.click(coords=(rect.right - 12, rect.mid_point().y))
    chat_list.type_keys("{END}")

    # 已处于多选模式（上次遍历残留）→ 直接返回最后的 CheckBox
    checkboxes = chat_list.children(control_type="CheckBox")
    if checkboxes:
        return checkboxes[-1]

    multiselect_item = main_window.child_window(**MenuItems.SelectMenuItem)

    # 从焦点消息向上跳过系统消息（与原实现一致）
    target = None
    while True:
        selected = [
            li for li in chat_list.children(control_type="ListItem")
            if li.has_keyboard_focus()
        ]
        if selected:
            if selected[0].class_name() != "mmui::ChatItemView":
                target = selected[0]
                break
        if not selected:
            break
        chat_list.type_keys("{UP}")
    if target is None:
        # 焦点丢失但可能残留多选状态
        checkboxes = chat_list.children(control_type="CheckBox")
        if checkboxes:
            return checkboxes[-1]
        print("未能在该聊天界面中找到任何可选中的消息!")
        return None

    # 构造右键候选位置：优先子元素（气泡/图片）中心，再用原库位置兜底
    r = target.rectangle()
    y_mid = (r.top + r.bottom) // 2
    candidates = []
    try:
        child_rects = [
            child.rectangle() for child in target.children()
        ]
        # 取面积最大的子元素（即消息气泡或图片），右键其中心
        valid = [cr for cr in child_rects if cr.width() > 30 and cr.height() > 12]
        if valid:
            bubble = max(valid, key=lambda cr: cr.width() * cr.height())
            mid = bubble.mid_point()
            candidates.append((mid.x, mid.y))
    except Exception:
        pass
    candidates += [
        (r.left + 120, r.bottom - 60),   # 原库位置（他人消息气泡）
        (r.right - 120, r.bottom - 60),  # 原库回退（自己消息气泡）
        (r.left + 120, y_mid),           # 垂直居中兜底（矮消息，bottom-60 会越界）
        (r.right - 120, y_mid),
    ]
    # 去重并保持顺序
    seen = set()
    unique_candidates = []
    for pos in candidates:
        key = (round(pos[0]), round(pos[1]))
        if key not in seen:
            seen.add(key)
            unique_candidates.append(pos)

    for pos in unique_candidates:
        mouse.right_click(coords=pos)
        if multiselect_item.exists(timeout=0.5):
            multiselect_item.click_input()
            mouse.click(coords=pos)  # 点击消息区域，恢复列表键盘焦点
            checkboxes = chat_list.children(control_type="CheckBox")
            if checkboxes:
                return checkboxes[-1]
            return target
        # 未弹出"多选"菜单 → ESC 关闭可能弹出的其他菜单，换位置重试
        try:
            import pyautogui

            pyautogui.press("esc")
        except Exception:
            pass
        time.sleep(0.2)

    raise RuntimeError("右键多个候选位置均未能打开'多选'菜单")


def _install_pyweixin_patches() -> None:
    """安装 pyweixin 运行时补丁（只装一次）

    用 _robust_select_chatlist 替换 Tools.select_chatList，修复右键定位
    失败导致的 title=多选 ElementNotFoundError。pull_messages 内部的
    traverse_message 通过类属性访问该方法，替换后立即生效。
    """
    global _PYWEIXIN_PATCHED
    if _PYWEIXIN_PATCHED:
        return
    try:
        from pyweixin.WeChatTools import Tools

        Tools.select_chatList = staticmethod(_robust_select_chatlist)
        _PYWEIXIN_PATCHED = True
        logger.info("已安装 pyweixin select_chatList 稳健性补丁")
    except Exception as e:
        logger.warning(f"安装 pyweixin 补丁失败(不影响运行): {e}")


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

            # 安装 pyweixin 稳健性补丁（修复 select_chatList 右键定位失败）
            _install_pyweixin_patches()

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
            # save_media 中途失败可能残留图片预览/聊天记录窗口，恢复 UI 状态
            # 避免残留弹窗导致后续 pull_messages 持续失败
            self._recover_wechat_ui_state()
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

    # ---- 微信 UI 状态自愈（针对 pywechat127 多选菜单卡死问题） ----

    @staticmethod
    def _find_wechat_hwnd() -> int:
        """查找微信主窗口句柄（微信 4.x 主窗口类名为 Qt51514QWindowIcon）"""
        try:
            import win32gui

            for title in ("微信", "Weixin"):
                hwnd = win32gui.FindWindow("Qt51514QWindowIcon", title)
                if hwnd:
                    return hwnd
        except Exception:
            pass
        return 0

    def _recover_wechat_ui_state(self, esc_count: int = 3) -> None:
        """恢复微信 UI 到干净状态（拉取消息失败后的自愈）

        pywechat127 的 pull_messages 内部依靠右键消息 → 点击「多选」菜单
        进入多选模式来遍历消息。一旦某次遍历中途异常（退出多选的 ESC 未执行），
        聊天区会残留在多选模式；此后右键消息弹出的菜单中不再包含「多选」项，
        导致 pull_messages 持续失败（报错 title=多选, type=MenuItem）。

        恢复策略：
            1. 找到微信主窗口并置前、聚焦，确保按键发到微信而不是其他窗口
            2. 连发多次 ESC：第一下关闭残留右键菜单，后续退出多选模式、
               关闭图片预览等弹窗（单次 ESC 只能关掉菜单，退不出多选模式）
            3. 校验聊天区是否仍处于多选模式（消息列表出现 CheckBox），
               若是则点击底部「取消」按钮强制退出

        任何步骤失败都只记录日志，不抛出异常。
        """
        try:
            import pyautogui

            hwnd = self._find_wechat_hwnd()
            if not hwnd:
                logger.warning("未找到微信主窗口，跳过 UI 状态恢复")
                return

            # 最小化则先还原
            try:
                import win32con
                import win32gui

                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            except Exception:
                pass

            # 将微信窗口带到前台并获得键盘焦点（多重降级保证）
            focused = False
            try:
                from pywinauto import Desktop

                Desktop(backend="uia").window(handle=hwnd).set_focus()
                focused = True
            except Exception:
                try:
                    import win32gui

                    win32gui.SetForegroundWindow(hwnd)
                    focused = True
                except Exception:
                    pass
            if not focused:
                # 最后手段：点击窗口标题栏激活（标题栏点击无业务副作用）
                try:
                    import win32gui

                    left, top, right, _bottom = win32gui.GetWindowRect(hwnd)
                    pyautogui.click(x=(left + right) // 2, y=top + 10)
                except Exception:
                    pass
            time.sleep(0.3)

            # 连发 ESC：关闭残留菜单 → 退出多选模式 → 关闭预览弹窗
            for _ in range(esc_count):
                pyautogui.press("esc")
                time.sleep(0.25)

            # 校验多选模式是否已退出，未退出则点击「取消」按钮
            if self._is_multiselect_active():
                logger.warning("ESC 后聊天区仍处于多选模式，尝试点击'取消'按钮")
                if self._click_multiselect_cancel():
                    time.sleep(0.3)
                    try:
                        pyautogui.press("esc")
                    except Exception:
                        pass
            logger.info(f"微信 UI 状态恢复完成（已发送 {esc_count} 次 ESC）")
        except Exception as e:
            logger.warning(f"微信 UI 状态恢复失败(可忽略): {e}")

    def _is_multiselect_active(self) -> bool:
        """检测当前聊天区是否处于多选模式（多选时消息列表会出现 CheckBox）"""
        try:
            from pyweixin.Uielements import Lists

            hwnd = self._find_wechat_hwnd()
            if not hwnd:
                return False
            from pywinauto import Desktop

            main_win = Desktop(backend="uia").window(handle=hwnd)
            chat_list = main_win.child_window(**Lists.FriendChatList)
            if not chat_list.exists(timeout=1):
                return False
            return bool(chat_list.children(control_type="CheckBox"))
        except Exception:
            return False

    def _click_multiselect_cancel(self) -> bool:
        """点击多选模式底部工具栏的「取消」按钮，退出多选"""
        try:
            from pyweixin.Uielements import Buttons

            hwnd = self._find_wechat_hwnd()
            if not hwnd:
                return False
            from pywinauto import Desktop

            main_win = Desktop(backend="uia").window(handle=hwnd)
            cancel_btn = main_win.child_window(**Buttons.CancelButton)
            if cancel_btn.exists(timeout=0.5):
                cancel_btn.click_input()
                logger.info("已点击多选模式'取消'按钮")
                return True
        except Exception as e:
            logger.debug(f"点击'取消'按钮失败: {e}")
        return False

    def _pull_messages_safe(self, friend: str, number: int = 5) -> list:
        """带 UI 状态自愈的 pull_messages 封装

        pywechat127 的 pull_messages 依赖右键菜单「多选」遍历消息，
        一旦聊天区残留多选模式/弹窗就会持续失败（title=多选, type=MenuItem）。
        本方法在每次失败后先恢复微信 UI 状态（聚焦微信 + 连发 ESC +
        点击取消按钮），最多尝试三轮，全部失败才放弃。
        """
        from pyweixin import Messages

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                msg_list = Messages.pull_messages(
                    friend=friend, number=number, close_weixin=False,
                )
                if attempt > 1:
                    logger.info(f"第 {attempt} 次拉取 '{friend}' 消息成功")
                return msg_list or []
            except Exception as err:
                err_desc = self._format_ui_error(err)
                if attempt < max_attempts:
                    logger.warning(
                        f"拉取 '{friend}' 消息第 {attempt} 次失败({err_desc})，"
                        f"恢复微信 UI 状态后重试"
                    )
                    # 第二次恢复加大 ESC 次数，应对更顽固的残留状态
                    self._recover_wechat_ui_state(
                        esc_count=3 if attempt == 1 else 5
                    )
                else:
                    logger.error(
                        f"拉取 '{friend}' 消息 {max_attempts} 次均失败({err_desc})，"
                        f"跳过该会话本轮消息"
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
