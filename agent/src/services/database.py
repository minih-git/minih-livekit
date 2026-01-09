"""
对话历史数据库模块 - SQLite 持久化存储

表结构:
- sessions: 会话记录（关联录音文件）
- messages: 消息记录
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 默认数据库路径
DEFAULT_DB_PATH = Path("data/chat.db")


@dataclass
class Session:
    """会话记录"""
    id: str
    room_name: str
    participant: Optional[str]
    started_at: datetime
    ended_at: Optional[datetime]
    recording_path: Optional[str]


@dataclass
class Message:
    """消息记录"""
    id: int
    session_id: str
    role: str  # 'user' or 'agent'
    content: str
    created_at: datetime


class ChatDatabase:
    """对话历史数据库管理器"""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        """
        初始化数据库连接
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        
        # 确保目录存在
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库
        self._init_db()
        logger.info(f"对话数据库已初始化: {db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    room_name TEXT NOT NULL,
                    participant TEXT,
                    started_at DATETIME NOT NULL,
                    ended_at DATETIME,
                    recording_path TEXT
                );
                
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_messages_session 
                ON messages(session_id);
            """)
            conn.commit()
        finally:
            conn.close()

    def create_session(
        self,
        session_id: str,
        room_name: str,
        participant: Optional[str] = None,
        recording_path: Optional[str] = None,
    ) -> str:
        """
        创建新会话
        
        Args:
            session_id: 会话唯一标识
            room_name: 房间名
            participant: 用户标识
            recording_path: 录音文件路径
            
        Returns:
            会话ID
        """
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO sessions (id, room_name, participant, started_at, recording_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, room_name, participant, datetime.now(), recording_path),
            )
            conn.commit()
            logger.info(f"创建会话: {session_id}")
            return session_id
        finally:
            conn.close()

    def end_session(self, session_id: str, recording_path: Optional[str] = None):
        """
        结束会话
        
        Args:
            session_id: 会话ID
            recording_path: 录音文件路径（可选更新）
        """
        conn = self._get_conn()
        try:
            if recording_path:
                conn.execute(
                    "UPDATE sessions SET ended_at = ?, recording_path = ? WHERE id = ?",
                    (datetime.now(), recording_path, session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET ended_at = ? WHERE id = ?",
                    (datetime.now(), session_id),
                )
            conn.commit()
            logger.info(f"会话结束: {session_id}")
        finally:
            conn.close()

    def add_message(self, session_id: str, role: str, content: str):
        """
        添加消息
        
        Args:
            session_id: 会话ID
            role: 角色 ('user' 或 'agent')
            content: 消息内容
        """
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, datetime.now()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_sessions(self, limit: int = 50) -> list[dict]:
        """
        获取会话列表
        
        Args:
            limit: 最大返回数量
            
        Returns:
            会话列表（包含消息数量）
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT s.*, COUNT(m.id) as message_count
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                GROUP BY s.id
                ORDER BY s.started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_session_messages(self, session_id: str) -> list[dict]:
        """
        获取会话的所有消息
        
        Args:
            session_id: 会话ID
            
        Returns:
            消息列表
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM messages 
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_session(self, session_id: str) -> Optional[dict]:
        """
        获取单个会话详情
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话信息或 None
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
