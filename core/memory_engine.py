from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "memory.db"
DB.parent.mkdir(parents=True, exist_ok=True)

SECRET_PATTERNS = [
    r"\bapi[_ -]?key\s*[:=]\s*\S+",
    r"\bpassword\s*[:=]\s*\S+",
    r"\botp\s*[:=]\s*\S+",
    r"\btoken\s*[:=]\s*\S+",
    r"\bauthorization\s*[:=]\s*\S+",
    r"\bprivate[_ -]?key\s*[:=]\s*\S+",
    r"\bcard[_ -]?number\s*[:=]\s*\S+",
    r"\bbearer\s+[A-Za-z0-9._~-]+",
]
SESSION_TIMEOUT_MINUTES = 60


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=10)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,last_activity TEXT NOT NULL,created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS conversation_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,user_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT NOT NULL,content TEXT NOT NULL,importance INTEGER NOT NULL DEFAULT 5,source TEXT NOT NULL DEFAULT 'conversation',updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_session ON conversation_messages(session_id,id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversation_messages(user_id,id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_activity ON sessions(last_activity)")
    conn.commit()


def looks_sensitive(text: str) -> bool:
    value = text or ""
    return any(re.search(pattern, value, re.I) for pattern in SECRET_PATTERNS)


def save_memory(category, content, importance=5, source="conversation"):
    if not content or looks_sensitive(content):
        return False
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            conn.execute("INSERT INTO memories(category,content,importance,source) VALUES(?,?,?,?)", (str(category), str(content), int(importance), str(source)))
        return True
    except sqlite3.Error:
        return False


def search_memory(keyword, limit=5):
    if not keyword:
        return []
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            return conn.execute("SELECT category,content,importance FROM memories WHERE content LIKE ? ORDER BY importance DESC,updated_at DESC LIMIT ?", (f"%{keyword}%", int(limit))).fetchall()
    except sqlite3.Error:
        return []


def get_or_create_session(user_id: int | str) -> str:
    now = datetime.now(timezone.utc)
    uid = str(user_id)
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT session_id,last_activity FROM sessions WHERE user_id=? ORDER BY last_activity DESC LIMIT 1", (uid,)).fetchone()
        if row:
            try:
                last = datetime.fromisoformat(row[1])
            except ValueError:
                last = now - timedelta(minutes=SESSION_TIMEOUT_MINUTES + 1)
            if now - last <= timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                conn.execute("UPDATE sessions SET last_activity=? WHERE session_id=?", (now.isoformat(), row[0]))
                return row[0]
        session_id = f"{uid}:{now.strftime('%Y%m%dT%H%M%S%fZ')}"
        conn.execute("INSERT INTO sessions(session_id,user_id,last_activity,created_at) VALUES(?,?,?,?)", (session_id, uid, now.isoformat(), now.isoformat()))
        return session_id


def touch_session(session_id: str) -> None:
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute("UPDATE sessions SET last_activity=? WHERE session_id=?", (datetime.now(timezone.utc).isoformat(), session_id))


def save_turn(session_id: str, user_id: int | str, role: str, content: str) -> bool:
    if role not in {"user", "assistant"} or not content or looks_sensitive(content):
        return False
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            conn.execute("INSERT INTO conversation_messages(session_id,user_id,role,content) VALUES(?,?,?,?)", (session_id, str(user_id), role, content))
            conn.execute("UPDATE sessions SET last_activity=? WHERE session_id=?", (datetime.now(timezone.utc).isoformat(), session_id))
        return True
    except sqlite3.Error:
        return False


def recent_turns(session_id: str, limit: int = 8):
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            rows = conn.execute("SELECT role,content FROM conversation_messages WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, int(limit))).fetchall()
        return list(reversed(rows))
    except sqlite3.Error:
        return []


def prune_old_sessions(days: int = 7) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            rows = conn.execute("SELECT session_id FROM sessions WHERE last_activity < ?", (cutoff.isoformat(),)).fetchall()
            for (session_id,) in rows:
                conn.execute("DELETE FROM conversation_messages WHERE session_id=?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            return len(rows)
    except sqlite3.Error:
        return 0
