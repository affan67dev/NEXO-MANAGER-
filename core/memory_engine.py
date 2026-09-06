import re
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "memory.db"

SECRET_PATTERNS = [
    r'api[_ -]?key',
    r'password',
    r'otp',
    r'token',
    r'authorization',
    r'private[_ -]?key',
    r'card[_ -]?number'
]

def looks_sensitive(text):
    value = text.lower()
    return any(re.search(pattern, value) for pattern in SECRET_PATTERNS)

def save_memory(category, content, importance=5, source="conversation"):
    if looks_sensitive(content):
        return False

    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT INTO memories(category, content, importance, source) VALUES (?, ?, ?, ?)",
            (category, content, importance, source)
        )
    return True

def search_memory(keyword, limit=5):
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            """SELECT category, content, importance
               FROM memories
               WHERE content LIKE ?
               ORDER BY importance DESC, updated_at DESC
               LIMIT ?""",
            (f"%{keyword}%", limit)
        ).fetchall()
    return rows
