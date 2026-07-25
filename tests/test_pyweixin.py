# https://github.com/Hello-Mr-Crab/pywechat
# pywechat (pyweixin 模块) 适配微信 4.x，安装: pip install pywechat127
#
# 运行前请确保:
#   1. Windows 上已运行微信 PC 客户端（4.1.x）并完成登录
#   2. pip install pywechat127  # pip install pywechat127 --user --no-cache-dir 2>&1
#   3. 微信窗口未被最小化到托盘

from pyweixin import Tools, Messages, Navigator, GlobalConfig

# 全局配置：不关闭微信主窗口
GlobalConfig.close_weixin = False
GlobalConfig.is_maximize = False


def test_login():
    """测试登录：通过 Tools.about_weixin() 获取微信基本信息，验证已连接并登录"""
    print("【测试】微信登录连接")
    try:
        info = Tools.about_weixin()
        print(f"\n\n------>连接成功，微信信息：{info}")
        print("✅ 登录测试通过\n")
        return True
    except Exception as e:
        print(f"❌ 登录测试失败: {e}")
        return False


def test_send_message():
    """测试发送消息：向文件传输助手发送一条测试消息"""
    print("=" * 50)
    print("【测试】发送消息")
    print("=" * 50)
    # target = "文件传输助手"
    target = "测试群"
    messages = ["你好，这是一条来自 pywechat 的测试消息", "测试完成 ✅"]
    try:
        Messages.send_messages_to_friend(friend=target, messages=messages)
        print(f"✅ 消息已发送给 '{target}': {messages}\n")
        return True
    except Exception as e:
        print(f"❌ 发送消息失败: {e}")
        return False


def test_session_list():
    """测试获取会话列表

    使用 Messages.dump_sessions() 获取会话列表，
    返回格式: [('发送人', '最后聊天时间', '最后聊天内容'), ...]
    """
    print("=" * 50)
    print("【测试】获取会话列表")
    print("=" * 50)
    try:
        sessions = Messages.dump_sessions(close_weixin=False)
        print(f"当前会话列表（共 {len(sessions)} 个）：")
        for s in sessions[:10]:  # 只显示前10个
            print(f"  - {s[0]}  最后消息时间: {s[1]}  最后内容: {s[2][:30]}")
        print("✅ 获取会话列表测试通过\n")
        return True
    except Exception as e:
        print(f"❌ 获取会话列表失败: {e}")
        return False


if __name__ == "__main__":
    results = []

    # 1. 登录测试
    results.append(("登录", test_login()))

    # 2. 获取会话列表
    results.append(("会话列表", test_session_list()))

    # 3. 发送消息测试
    results.append(("发送消息", test_send_message()))

    # 汇总
    print("=" * 50)
    print("测试汇总")
    print("=" * 50)
    for name, ok in results:
        print(f"{'✅' if ok else '❌'} {name}")
