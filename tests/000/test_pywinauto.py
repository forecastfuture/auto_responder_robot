from pywinauto import Application
from pywinauto.keyboard import send_keys

# 连接微信（微信4.x 可能存在多个标题含"微信"的窗口，用 found_index 指定第一个）
app = Application(backend="uia").connect(title_re=".*微信.*", found_index=0)

win = app.top_window()
win.set_focus()

# Ctrl+F
send_keys("^f")

# 搜索联系人
send_keys("文件传输助手")
send_keys("{ENTER}")

# 输入消息
send_keys("你好")
send_keys("{ENTER}")