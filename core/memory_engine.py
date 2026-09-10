from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "memory.db"
DB.parent.mkdir(parents=True, exist_ok=True)

SECRET_PATTERNS = [
    r"api[_ -]?key",
    r"password",
    r"otp",
    r"token",
    r"authorization",
    r"private[_ -]?key",
    r"card[_ -]?number",
    r"bearer\s+[A-Za-z0-9._-]+",
]

SESSION_TIMEOUT_MINUTES = 60


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=10)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions(
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            last_activity TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS conversation_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_session ON conversation_messages(session_id, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_user ON conversation_messages(user_id, id)"
    )
    conn.commit()


def looks_sensitive(text: str) -> bool:
    value = text.lower()
    return any(re.search(pattern, value) for pattern in SECRET_PATTERNS)


def save_memory(category, content, importance=5, source="conversation"):
    if not content or looks_sensitive(content):
        return False

    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO memories(category, content, importance, source) VALUES (?, ?, ?, ?)",
            (category, content, importance, source),
        )
    return True


def search_memory(keyword, limit=5):
    if not keyword:
        return []
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """SELECT category, content, importance
               FROM memories
               WHERE content LIKE ?
               ORDER BY importance DESC, updated_at DESC
               LIMIT ?""",
            (f"%{keyword}%", limit),
        ).fetchall()
    return rows


def get_or_create_session(user_id: int | str) -> str:
    now = datetime.now(timezone.utc)
    uid = str(user_id)
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT session_id, last_activity FROM sessions WHERE user_id=? ORDER BY last_activity DESC LIMIT 1",
            (uid,),
        ).fetchone()

        if row:
            try:
                last = datetime.fromisoformat(row[1])
            except ValueError:
                last = now - timedelta(minutes=SESSION_TIMEOUT_MINUTES + 1)
            if now - last <= timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                conn.execute(
                    "UPDATE sessions SET last_activity=? WHERE session_id=?",
                    (now.isoformat(), row[0]),
                )
                conn.commit()
                return row[0]

        session_id = f"{uid}:{now.strftime('%Y%m%dT%H%M%S%fZ')}"
        conn.execute(
            "INSERT INTO sessions(session_id,user_id,last_activity,created_at) VALUES(?,?,?,?)",
            (session_id, uid, now.isoformat(), now.isoformat()),
        )
        conn.commit()
        return session_id


def touch_session(session_id: str) -> None:
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            "UPDATE sessions SET last_activity=? WHERE session_id=?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )


def save_turn(session_id: str, user_id: int | str, role: str, content: str) -> bool:
    if role not in {"user", "assistant"} or not content or looks_sensitive(content):
        return False
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO conversation_messages(session_id,user_id,role,content) VALUES(?,?,?,?)",
            (session_id, str(user_id), role, content),
        )
        conn.execute(
            "UPDATE sessions SET last_activity=? WHERE session_id=?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )
    return True


def recent_turns(session_id: str, limit: int = 8):
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """SELECT role, content FROM conversation_messages
               WHERE session_id=? ORDER BY id DESC LIMIT ?""",
            (session_id, limit),
        ).fetchall()
    return list(reversed(rows))


def prune_old_sessions(days: int = 7) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with _connect() as conn:
        _ensure_schema(conn)
        sessions = conn.execute(
            "SELECT session_id FROM sessions WHERE last_activity < ?",
            (cutoff.isoformat(),),
        ).fetchall()
        for (session_id,) in sessions:
            conn.execute("DELETE FROM conversation_messages WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
    return len(sessions)
