"""Legacy RAG compatibility wrapper with mandatory user scoping."""
import os
import re
import sqlite3

DB = os.path.expanduser("~/NEXO/data/memory.db")

def _tokens(text):
    return set(re.findall(r"[a-zA-Z0-9_]{3,}", text.lower()))

def retrieve(query, user_id=None, limit=8):
    if user_id is None:
        return []
    q = _tokens(query or "")
    if not q or not os.path.exists(DB):
        return []
    con = sqlite3.connect(DB)
    try:
        rows = con.execute(
            "SELECT category,content,importance,source,created_at,updated_at FROM memories WHERE user_id=? ORDER BY importance DESC,id DESC LIMIT 500",
            (str(user_id),),
        ).fetchall()
    except Exception:
        return []
    finally:
        con.close()
    scored = []
    for row in rows:
        text = " ".join(str(x) for x in row if x is not None)
        score = len(q & _tokens(text))
        if score:
            scored.append((score, text))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[:max(1, min(int(limit), 20))]]

def build_context(query, user_id=None):
    items = retrieve(query, user_id=user_id)
    return "\n\n".join(f"[MEMORY {i+1}] {x}" for i, x in enumerate(items))
