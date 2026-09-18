"""Operational history stored in the existing SQLite memory database."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

DB = Path(__file__).resolve().parents[1] / "data" / "memory.db"
logger = logging.getLogger("nexo.operational_history")


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _init(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS operational_history "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_operational_history_created ON operational_history(created_at)")


def record_event(event_type: str, payload: dict[str, Any]) -> bool:
    conn = _conn()
    try:
        _init(conn)
        conn.execute(
            "INSERT INTO operational_history(event_type,payload,created_at) VALUES(?,?,?)",
            (str(event_type)[:100], json.dumps(payload, ensure_ascii=False)[:12000], time.time()),
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.exception("operational_history_write_failed error=%s", type(exc).__name__)
        return False
    finally:
        conn.close()


def search_events(query: str = "", limit: int = 10) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()[:500]
    limit = max(1, min(int(limit), 50))
    conn = _conn()
    try:
        _init(conn)
        rows = conn.execute(
            "SELECT id,event_type,payload,created_at FROM operational_history ORDER BY id DESC LIMIT ?",
            (limit * 5,),
        ).fetchall()
        out = []
        for rid, typ, payload, created in rows:
            try:
                data = json.loads(payload)
            except Exception:
                data = {"raw": payload}
            if not q or q in (typ + " " + json.dumps(data, ensure_ascii=False)).lower():
                out.append({"id": rid, "event_type": typ, "payload": data, "created_at": created})
                if len(out) >= limit:
                    break
        return out
    except Exception as exc:
        logger.exception("operational_history_read_failed error=%s", type(exc).__name__)
        return []
    finally:
        conn.close()
