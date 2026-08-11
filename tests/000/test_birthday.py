"""生日提醒测试 - 测试生日记录管理和查询"""

import os
import tempfile
from datetime import datetime
import pytest

from tools.birthday import BirthdayManager


@pytest.fixture
def birthday_mgr():
    """创建临时生日管理器"""
    db_path = os.path.join(tempfile.mkdtemp(), "test_birthday.db")
    mgr = BirthdayManager(db_path=db_path)
    yield mgr


class TestBirthdayManager:
    """BirthdayManager 测试"""

    def test_add_birthday(self, birthday_mgr):
        """测试添加生日"""
        bid = birthday_mgr.add_birthday("张三", "1995-06-01", "朋友群")
        assert bid > 0

        all_birthdays = birthday_mgr.get_all_birthdays()
        assert len(all_birthdays) == 1
        assert all_birthdays[0][0] == "张三"
        assert all_birthdays[0][1] == "1995-06-01"
        assert all_birthdays[0][2] == "朋友群"

    def test_add_multiple_birthday(self, birthday_mgr):
        """测试添加多个生日"""
        birthday_mgr.add_birthday("张三", "1995-06-01", "朋友群")
        birthday_mgr.add_birthday("李四", "1998-08-10", "技术群")
        birthday_mgr.add_birthday("王五", "1992-12-25", "朋友群")

        all_birthdays = birthday_mgr.get_all_birthdays()
        assert len(all_birthdays) == 3

    def test_get_today_birthday(self, birthday_mgr):
        """测试获取今日生日"""
        today = datetime.now()
        today_md = today.strftime("%m-%d")
        today_ymd = today.strftime("%Y-%m-%d")

        # 添加今天生日的人
        birthday_mgr.add_birthday("今天寿星", f"1990-{today_md}", "朋友群")
        # 添加不是今天生日的人
        birthday_mgr.add_birthday("不是今天", "1990-01-01", "朋友群")

        today_birthdays = birthday_mgr.get_today_birthdays()
        assert len(today_birthdays) == 1
        assert today_birthdays[0][0] == "今天寿星"
        assert today_birthdays[0][2] == "朋友群"

    def test_no_today_birthday(self, birthday_mgr):
        """测试今日无人生日"""
        birthday_mgr.add_birthday("张三", "1995-01-01", "朋友群")

        today_birthdays = birthday_mgr.get_today_birthdays()
        # 如果今天恰好是1月1日，这个测试会失败，但概率极低
        if datetime.now().strftime("%m-%d") != "01-01":
            assert len(today_birthdays) == 0

    def test_remove_birthday(self, birthday_mgr):
        """测试删除生日"""
        birthday_mgr.add_birthday("张三", "1995-06-01", "朋友群")
        birthday_mgr.add_birthday("李四", "1998-08-10", "技术群")

        birthday_mgr.remove_birthday("张三")

        all_birthdays = birthday_mgr.get_all_birthdays()
        assert len(all_birthdays) == 1
        assert all_birthdays[0][0] == "李四"

    def test_remove_birthday_by_group(self, birthday_mgr):
        """测试按群删除生日"""
        birthday_mgr.add_birthday("张三", "1995-06-01", "朋友群")
        birthday_mgr.add_birthday("张三", "1995-06-01", "技术群")

        birthday_mgr.remove_birthday("张三", "朋友群")

        all_birthdays = birthday_mgr.get_all_birthdays()
        assert len(all_birthdays) == 1
        assert all_birthdays[0][2] == "技术群"

    def test_build_birthday_prompt(self, birthday_mgr):
        """测试生日祝福提示词构建"""
        prompt = birthday_mgr.build_birthday_prompt("张三")
        assert "张三" in prompt
        assert "生日" in prompt

    def test_empty_birthday_list(self, birthday_mgr):
        """测试空生日列表"""
        all_birthdays = birthday_mgr.get_all_birthdays()
        assert len(all_birthdays) == 0

        today_birthdays = birthday_mgr.get_today_birthdays()
        assert len(today_birthdays) == 0
