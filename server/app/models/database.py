"""
SQLite 数据库持久化层
使用 aiosqlite 异步操作，提供会话和消息的 CRUD 接口
"""
import os
from pathlib import Path
from typing import Optional

import aiosqlite

from ..common.config import get_settings
from ..common.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# 数据库初始化
# ============================================================

CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id   TEXT    UNIQUE NOT NULL,
    title       TEXT    DEFAULT '新的聊天',
    created_at  TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT    DEFAULT (datetime('now', 'localtime'))
);
"""

CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id   TEXT    NOT NULL,
    role        TEXT    NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content     TEXT    NOT NULL,
    tool_name   TEXT,
    created_at  TEXT    DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (thread_id) REFERENCES sessions(thread_id) ON DELETE CASCADE
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id);",
    "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC);",
]


async def init_database(db_path: Optional[str] = None) -> aiosqlite.Connection:
    """初始化数据库连接，创建表结构和索引"""
    settings = get_settings()
    path = db_path or str(settings.sqlite_db_path_abs)

    # 确保父目录存在
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"正在连接 SQLite 数据库: {path}")
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row

    # 启用外键约束
    await db.execute("PRAGMA foreign_keys = ON;")
    # 启用 WAL 模式提升并发性能
    await db.execute("PRAGMA journal_mode=WAL;")

    # 创建表
    await db.execute(CREATE_SESSIONS_TABLE)
    await db.execute(CREATE_MESSAGES_TABLE)
    for index_sql in CREATE_INDEXES:
        await db.execute(index_sql)

    await db.commit()
    logger.info("数据库表初始化完成")
    return db


# ============================================================
# 会话仓库
# ============================================================

class SessionRepository:
    """会话数据访问层"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def create(self, thread_id: str, title: str = "新的聊天") -> dict:
        """创建新会话"""
        await self.db.execute(
            "INSERT INTO sessions (thread_id, title) VALUES (?, ?)",
            (thread_id, title),
        )
        await self.db.commit()
        return await self.get_by_thread_id(thread_id)

    async def get_all(self) -> list[dict]:
        """获取所有会话，按更新时间降序"""
        cursor = await self.db.execute(
            "SELECT id, thread_id, title, created_at, updated_at "
            "FROM sessions ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_by_thread_id(self, thread_id: str) -> Optional[dict]:
        """根据 thread_id 获取会话"""
        cursor = await self.db.execute(
            "SELECT id, thread_id, title, created_at, updated_at "
            "FROM sessions WHERE thread_id = ?",
            (thread_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete(self, thread_id: str) -> bool:
        """删除会话及关联消息（CASCADE）"""
        cursor = await self.db.execute(
            "DELETE FROM sessions WHERE thread_id = ?",
            (thread_id,),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def update_timestamp(self, thread_id: str) -> None:
        """更新会话的最后活跃时间"""
        await self.db.execute(
            "UPDATE sessions SET updated_at = datetime('now', 'localtime') WHERE thread_id = ?",
            (thread_id,),
        )
        await self.db.commit()

    async def update_title(self, thread_id: str, title: str) -> None:
        """更新会话标题"""
        await self.db.execute(
            "UPDATE sessions SET title = ? WHERE thread_id = ?",
            (title, thread_id),
        )
        await self.db.commit()


# ============================================================
# 消息仓库
# ============================================================

class MessageRepository:
    """消息数据访问层"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def save(
        self, thread_id: str, role: str, content: str, tool_name: Optional[str] = None
    ) -> dict:
        """保存一条消息"""
        cursor = await self.db.execute(
            "INSERT INTO messages (thread_id, role, content, tool_name) VALUES (?, ?, ?, ?)",
            (thread_id, role, content, tool_name),
        )
        await self.db.commit()
        return {
            "id": cursor.lastrowid,
            "thread_id": thread_id,
            "role": role,
            "content": content,
            "tool_name": tool_name,
        }

    async def get_by_thread_id(self, thread_id: str) -> list[dict]:
        """获取指定会话的所有消息，按创建时间升序"""
        cursor = await self.db.execute(
            "SELECT id, thread_id, role, content, tool_name, created_at "
            "FROM messages WHERE thread_id = ? ORDER BY created_at ASC",
            (thread_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_by_thread_id(self, thread_id: str) -> int:
        """清空指定会话的所有消息"""
        cursor = await self.db.execute(
            "DELETE FROM messages WHERE thread_id = ?",
            (thread_id,),
        )
        await self.db.commit()
        return cursor.rowcount

    async def get_recent_messages(self, thread_id: str, limit: int = 50) -> list[dict]:
        """获取会话最近 N 条消息"""
        cursor = await self.db.execute(
            "SELECT id, thread_id, role, content, tool_name, created_at "
            "FROM messages WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?",
            (thread_id, limit),
        )
        rows = await cursor.fetchall()
        # 反转回时间升序
        return [dict(row) for row in reversed(rows)]
