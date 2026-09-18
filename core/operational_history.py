"""Small operational-history store using the existing memory database."""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DB = Path(__file__).resolve().parents[1] / "data" / "memory.db"

def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.execute("PRAGMA busy_timeout=10000")
    return c

def _init(c):
    c.execute("""CREATE TABLE IF NOT EXISTS operational_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at REAL NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_operational_history_created ON operational_history(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_operational_history_type ON operational_history(event_type)")

def record_event(event_type: str, payload: dict[str, Any]) -> bool:
    try:
        with _conn() as c:
            _init(c)
            c.execute("INSERT INTO operational_history(event_type,payload,created_at) VALUES(?,?,?)",
                      (str(event_type)[:100], json.dumps(payload, ensure_ascii=False)[:12000], time.time()))
        return True
    except Exception:
        return False

def search_events(query: str = "", limit: int = 10) -> list[dict[str, Any]]:
    query = (query or "").strip().lower()[:500]
    limit = max(1, min(int(limit), 50))
    try:
        with _conn() as c:
            _init(c)
            rows = c.execute("SELECT id,event_type,payload,created_at FROM operational_history ORDER BY id DESC LIMIT ?",
                             (limit * 5,)).fetchall()
        out=[]
        for row in rows:
            try: payload=json.loads(row[2])
            except Exception: payload={"raw": row[2]}
            blob=(row[1]+" "+json.dumps(payload,ensure_ascii=False)).lower()
            if not query or query in blob:
                out.append({"id":row[0],"event_type":row[1],"payload":payload,"created_at":row[3]})
                if len(out)>=limit: break
        return out
    except Exception:
        return []
