from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "memory.db"
DB.parent.mkdir(parents=True, exist_ok=True)

SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|otp)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]+"),
    re.compile(r"(?i)-----BEGIN(?: [A-Z]+)* PRIVATE KEY-----"),
    re.compile(r"(?i)\b(card[_ -]?number|authorization)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:sk|rk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\b(?:ghp_|github_pat_|gsk_|AIza)[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
)
MAX_CONTENT_CHARS = 12000

@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB, timeout=10)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        yield conn
    finally:
        conn.close()


def _schema(c: sqlite3.Connection) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS semantic_memory(id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general', importance INTEGER NOT NULL DEFAULT 5, source TEXT NOT NULL DEFAULT 'conversation', hash TEXT UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    columns = {row[1] for row in c.execute("PRAGMA table_info(semantic_memory)").fetchall()}
    if "user_id" not in columns:
        c.execute("ALTER TABLE semantic_memory ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
    c.execute("CREATE INDEX IF NOT EXISTS idx_semantic_memory_user ON semantic_memory(user_id,importance,id)")
    c.commit()


def looks_sensitive(text: str) -> bool:
    value = text or ""
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


class SemanticMemory:
    def __init__(self) -> None:
        self.client = None
        self.collection = None
        try:
            import chromadb
        except Exception:
            chromadb = None
        if chromadb is not None:
            try:
                path = str(BASE / "data" / "chroma")
                self.client = chromadb.PersistentClient(path=path)
                self.collection = self.client.get_or_create_collection("nexo_memory")
            except Exception:
                self.client = self.collection = None

    def add(self, content: str, category: str = "general", importance: int = 5, source: str = "conversation", user_id: int | str | None = None) -> bool:
        content = (content or "").strip()
        if not content or len(content) > MAX_CONTENT_CHARS or looks_sensitive(content):
            return False
        importance = max(1, min(int(importance), 10))
        uid = str(user_id or "")
        digest = hashlib.sha256(f"{uid}\0{content}".encode()).hexdigest()
        try:
            with _conn() as c:
                _schema(c)
                c.execute("INSERT OR IGNORE INTO semantic_memory(content,category,importance,source,hash,user_id) VALUES(?,?,?,?,?,?)", (content, str(category), importance, str(source), digest, uid))
            if self.collection:
                self.collection.upsert(ids=[digest], documents=[content], metadatas=[{"category": str(category), "importance": importance, "source": str(source), "user_id": uid}])
            return True
        except Exception:
            return False

    def search(self, query: str, limit: int = 5, user_id: int | str | None = None) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        safe_limit = max(1, min(int(limit), 10))
        uid = str(user_id or "")
        if self.collection:
            try:
                count = self.collection.count()
                if count > 0:
                    r = self.collection.query(query_texts=[query], n_results=min(safe_limit, count), where={"user_id": uid})
                    docs = (r.get("documents") or [[]])[0]
                    metas = (r.get("metadatas") or [[]])[0]
                    return [{"content": d, "metadata": m or {}} for d, m in zip(docs, metas) if isinstance(d, str)]
            except Exception:
                pass
        with _conn() as c:
            _schema(c)
            rows = c.execute("SELECT content,category,importance,source FROM semantic_memory WHERE user_id=? AND content LIKE ? ORDER BY importance DESC, id DESC LIMIT ?", (uid, f"%{query}%", safe_limit)).fetchall()
        return [{"content": r[0], "metadata": {"category": r[1], "importance": r[2], "source": r[3]}} for r in rows]


memory = SemanticMemory()
