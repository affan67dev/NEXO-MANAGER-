"""Operational history stored in the existing SQLite memory database."""
from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
from typing import Any
DB=Path(__file__).resolve().parents[1]/"data"/"memory.db"
def _conn():
    DB.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(DB,timeout=10); c.execute("PRAGMA busy_timeout=10000"); return c
def _init(c):
    c.execute("CREATE TABLE IF NOT EXISTS operational_history (id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_operational_history_created ON operational_history(created_at)")
def record_event(event_type:str,payload:dict[str,Any])->bool:
    try:
        with _conn() as c:
            _init(c); c.execute("INSERT INTO operational_history(event_type,payload,created_at) VALUES(?,?,?)",(str(event_type)[:100],json.dumps(payload,ensure_ascii=False)[:12000],time.time()))
        return True
    except Exception:return False
def search_events(query:str="",limit:int=10)->list[dict[str,Any]]:
    q=(query or "").strip().lower()[:500]; limit=max(1,min(int(limit),50))
    try:
        with _conn() as c:
            _init(c); rows=c.execute("SELECT id,event_type,payload,created_at FROM operational_history ORDER BY id DESC LIMIT ?",(limit*5,)).fetchall()
        out=[]
        for rid,typ,payload,created in rows:
            try:data=json.loads(payload)
            except Exception:data={"raw":payload}
            if not q or q in (typ+" "+json.dumps(data,ensure_ascii=False)).lower():
                out.append({"id":rid,"event_type":typ,"payload":data,"created_at":created})
                if len(out)>=limit:break
        return out
    except Exception:return []
