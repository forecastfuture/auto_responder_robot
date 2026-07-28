"""记忆系统 - 基于 SQLite 的对话历史和长期记忆存储

数据库表结构:
    messages: 对话历史记录
        - id, user_id, user_name, group_name, content, role, timestamp
    memories: 提取的长期记忆
        - id, user_name, content, importance, timestamp
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional

from utils.set_logger import get_logger

logger = get_logger()


class MemoryManager:
    """记忆管理器 - 管理对话历史和长期记忆"""

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化记忆管理器

        Args:
            db_path: SQLite 数据库路径，默认为项目目录下 data/bot.db
        """
        if db_path is None:
            db_path = "data/bot.db"
        self.db_path = db_path
        self._init_db()
        logger.info(f"记忆系统初始化完成, db={db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        import os
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表"""
        with self._get_conn() as conn:
            # 对话历史表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT DEFAULT '',
                    user_name TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    role TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            # 长期记忆表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    timestamp TEXT NOT NULL
                )
                """
            )
            # 生日表
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
            # 创建索引
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_group ON messages(group_name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_name)"
            )

    # ==================== 对话历史 ====================

    def add_message(
        self,
        user_name: str,
        group_name: str,
        content: str,
        role: str,
        user_id: str = "",
    ):
        """
        添加一条对话记录

        Args:
            user_name: 发送者名称
            group_name: 群名
            content: 消息内容
            role: 角色 (user/assistant)
            user_id: 用户 ID（可选）
        """
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO messages (user_id, user_name, group_name, content, role, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    user_name,
                    group_name,
                    content,
                    role,
                    datetime.now().isoformat(),
                ),
            )

    def get_recent_history(
        self, group_name: str, limit: int = 10
    ) -> List[Dict[str, str]]:
        """
        获取某个群最近的对话历史

        Args:
            group_name: 群名
            limit: 记录数量

        Returns:
            对话历史列表，格式为 [{"role": "user/assistant", "content": "..."}, ...]
            按时间顺序排列
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT user_name, content, role FROM messages "
                "WHERE group_name = ? ORDER BY id DESC LIMIT ?",
                (group_name, limit),
            ).fetchall()

        # 倒序查询后反转为正序
        rows = list(reversed(rows))
        history = []
        for row in rows:
            if row["role"] == "user":
                history.append(
                    {"role": "user", "content": f"{row['user_name']}: {row['content']}"}
                )
            else:
                history.append({"role": "assistant", "content": row["content"]})
        return history

    # ==================== 长期记忆 ====================

    def add_memory(
        self, user_name: str, content: str, importance: float = 0.5
    ):
        """
        添加一条长期记忆

        Args:
            user_name: 用户名
            content: 记忆内容
            importance: 重要性 (0-1)
        """
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO memories (user_name, content, importance, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (user_name, content, importance, datetime.now().isoformat()),
            )
        logger.info(f"添加记忆: user={user_name}, content={content[:50]}...")

    def get_memories(
        self, user_name: str, limit: int = 5
    ) -> List[str]:
        """
        获取某用户的长期记忆

        Args:
            user_name: 用户名
            limit: 最多返回数量

        Returns:
            记忆内容列表
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT content FROM memories WHERE user_name = ? "
                "ORDER BY importance DESC, id DESC LIMIT ?",
                (user_name, limit),
            ).fetchall()
        return [row["content"] for row in rows]

    def build_memory_context(self, user_name: str) -> str:
        """
        构建记忆上下文文本

        Args:
            user_name: 用户名

        Returns:
            记忆上下文文本，如果没有记忆则返回空字符串
        """
        memories = self.get_memories(user_name)
        if not memories:
            return ""
        return f"关于{user_name}的记忆: {'; '.join(memories)}"
