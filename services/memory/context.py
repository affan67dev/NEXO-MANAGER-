"""Compatibility memory reader with mandatory user scoping."""
import os
import sqlite3

DB = os.path.expanduser("~/NEXO/data/memory.db")

def recent(user_id: int | str | None = None, limit: int = 20):
    if user_id is None:
        return []
    con = sqlite3.connect(DB)
    try:
        return con.execute(
            "SELECT * FROM memories WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (str(user_id), max(1, min(int(limit), 20))),
        ).fetchall()
    except Exception:
        return []
    finally:
        con.close()
