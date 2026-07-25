
from wxauto4 import WeChat # 免费版
# from wxautox4 import WeChat  # Plus版

# 初始化微信实例
wx = WeChat()

# 切换到文件传输助手
target = "文件传输助手"
wx.ChatWith(target)

# 查看当前窗口信息
chatinfo = wx.ChatInfo()
print(f"当前窗口信息：{chatinfo}")

# 发送消息
if chatinfo.get('chat_name') == target:  # 先判断是否为要发送的人
    wx.SendMsg("你好")

# 获取当前聊天窗口消息
msgs = wx.GetAllMessage()

for msg in msgs:
    print(msg.raw)


