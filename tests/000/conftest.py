"""pytest 全局配置 - 设置测试环境和路径"""

import sys
import os
import tempfile

# 将项目根目录加入 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 测试用临时数据库路径
TEST_DB_DIR = tempfile.mkdtemp(prefix="bot_test_")


def get_test_db_path():
    """获取测试用临时数据库路径"""
    return os.path.join(TEST_DB_DIR, f"test_bot_{os.getpid()}.db")
