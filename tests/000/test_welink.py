from weilink import WeiLink
wl = WeiLink()
wl.login()                    # 扫码登录
messages = wl.recv()          # 接收消息
for msg in messages:
    print(f"{msg.from_user}: {msg.text}")
    wl.send(msg.from_user, "收到！")  # 回复
wl.close()

# 垃圾 下一个

