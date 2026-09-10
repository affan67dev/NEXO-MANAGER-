from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "memory.db"
DB.parent.mkdir(parents=True, exist_ok=True)

try:
    import chromadb
except Exception:
    chromadb = None


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=10000")
    return c


def _schema(c: sqlite3.Connection) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS semantic_memory(id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general', importance INTEGER NOT NULL DEFAULT 5, source TEXT NOT NULL DEFAULT 'conversation', hash TEXT UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    c.commit()

class SemanticMemory:
    def __init__(self) -> None:
        self.client = None
        self.collection = None
        if chromadb is not None:
            try:
                path = str(BASE / "data" / "chroma")
                self.client = chromadb.PersistentClient(path=path)
                self.collection = self.client.get_or_create_collection("nexo_memory")
            except Exception:
                self.client = self.collection = None

    def add(self, content: str, category: str = "general", importance: int = 5, source: str = "conversation") -> bool:
        content = (content or "").strip()
        if not content:
            return False
        digest = hashlib.sha256(content.encode()).hexdigest()
        try:
            with _conn() as c:
                _schema(c)
                c.execute("INSERT OR IGNORE INTO semantic_memory(content,category,importance,source,hash) VALUES(?,?,?,?,?)", (content, category, int(importance), source, digest))
            if self.collection:
                self.collection.upsert(ids=[digest], documents=[content], metadatas=[{"category": category, "importance": int(importance), "source": source}])
            return True
        except Exception:
            return False

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        if self.collection:
            try:
                r = self.collection.query(query_texts=[query], n_results=max(1, int(limit)))
                docs = (r.get("documents") or [[]])[0]
                metas = (r.get("metadatas") or [[]])[0]
                return [{"content": d, "metadata": m or {}} for d, m in zip(docs, metas)]
            except Exception:
                pass
        with _conn() as c:
            _schema(c)
            rows = c.execute("SELECT content,category,importance,source FROM semantic_memory WHERE content LIKE ? ORDER BY importance DESC, id DESC LIMIT ?", (f"%{query}%", int(limit))).fetchall()
        return [{"content": r[0], "metadata": {"category": r[1], "importance": r[2], "source": r[3]}} for r in rows]

memory = SemanticMemory()
