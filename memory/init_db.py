import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "memory.db"
SCHEMA = BASE / "memory" / "schema.sql"

DB.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(DB) as conn:
    conn.executescript(SCHEMA.read_text())

print(f"✅ NEXO memory database ready: {DB}")
