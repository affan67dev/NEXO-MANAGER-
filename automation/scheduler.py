import sqlite3
from pathlib import Path
from datetime import datetime

BASE=Path(__file__).resolve().parent.parent
DB=BASE/"data"/"memory.db"

def add_task(name,task_type,run_at,details=""):
    with sqlite3.connect(DB) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS automations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        task_type TEXT NOT NULL,
        run_at TEXT NOT NULL,
        details TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("INSERT INTO automations(name,task_type,run_at,details) VALUES(?,?,?,?)",(name,task_type,run_at,details))

def list_tasks():
    with sqlite3.connect(DB) as db:
        return db.execute("SELECT id,name,task_type,run_at,status,details FROM automations ORDER BY run_at").fetchall()
