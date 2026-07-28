"""生日提醒 - 管理生日记录并生成生日祝福

数据库表结构（复用 bot.db）:
    birthdays:
        - id, name, birthday (YYYY-MM-DD), group_name
"""

import sqlite3
import logging
import os
from datetime import datetime
from typing import List, Tuple, Optional

from utils.set_logger import get_logger

logger = get_logger()


class BirthdayManager:
    """生日管理器"""

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化生日管理器

        Args:
            db_path: SQLite 数据库路径
        """
        if db_path is None:
            db_path = "data/bot.db"
        self.db_path = db_path
        self._init_db()
        logger.info("生日提醒管理器初始化完成")

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化生日表"""
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS birthdays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    birthday TEXT NOT NULL,
                    group_name TEXT
                )
                """
            )

    def add_birthday(
        self, name: str, birthday: str, group_name: Optional[str] = None
    ) -> int:
        """
        添加生日记录

        Args:
            name: 姓名
            birthday: 生日日期，格式 YYYY-MM-DD
            group_name: 所在群名

        Returns:
            新记录 ID
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO birthdays (name, birthday, group_name) VALUES (?, ?, ?)",
                (name, birthday, group_name),
            )
            logger.info(f"添加生日记录: name={name}, birthday={birthday}, group={group_name}")
            return cursor.lastrowid

    def remove_birthday(self, name: str, group_name: Optional[str] = None):
        """
        移除生日记录

        Args:
            name: 姓名
            group_name: 群名（可选，用于精确匹配）
        """
        with self._get_conn() as conn:
            if group_name:
                conn.execute(
                    "DELETE FROM birthdays WHERE name = ? AND group_name = ?",
                    (name, group_name),
                )
            else:
                conn.execute("DELETE FROM birthdays WHERE name = ?", (name,))
            logger.info(f"移除生日记录: name={name}")

    def get_today_birthdays(self) -> List[Tuple[str, str, Optional[str]]]:
        """
        获取今天过生日的人

        Returns:
            列表 [(name, birthday, group_name), ...]
        """
        today = datetime.now().strftime("%m-%d")
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT name, birthday, group_name FROM birthdays "
                "WHERE strftime('%m-%d', birthday) = ?",
                (today,),
            ).fetchall()

        results = [(row["name"], row["birthday"], row["group_name"]) for row in rows]
        if results:
            logger.info(f"今天过生日的人: {results}")
        return results

    def get_all_birthdays(self) -> List[Tuple[str, str, Optional[str]]]:
        """
        获取所有生日记录

        Returns:
            列表 [(name, birthday, group_name), ...]
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT name, birthday, group_name FROM birthdays ORDER BY birthday"
            ).fetchall()
        return [(row["name"], row["birthday"], row["group_name"]) for row in rows]

    def build_birthday_prompt(self, name: str) -> str:
        """
        构建生日祝福生成提示词

        Args:
            name: 过生日的人名

        Returns:
            提示词
        """
        return (
            f"今天是{name}的生日，请你生成一句生日祝福群消息。"
            f"要求：有温度、不要太长、自然口语化、适合在微信群里发。"
            f"可以在祝福里带上{name}的名字。"
        )
