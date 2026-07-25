from wcferry import Wcf

# 初始化客户端
wcf = Wcf()
# 建立连接（通常在 start 或 connect 中）
wcf.start()   # 或 wcf.connect()，请参考官方示例
wcf.send_text(to_user="张三", content="会议改至14:30", at_list=["@李四"])
wcf.send_file(to_user="工作群", file_path="C:/report.pdf")