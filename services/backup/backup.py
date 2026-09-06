from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime,timezone

def backup_sqlite(source: str, destination_dir: str = "data/backups") -> dict:
    src = Path(source)
    root = Path(__file__).resolve().parents[2]
    if not src.is_absolute():
        src = root / src

    if not src.exists():
        return {"status":"NOT_CREATED","reason":"database_missing","path":str(src)}

    out_dir = root / destination_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / f"database_{stamp}.sqlite"

    source_db = sqlite3.connect(src)
    backup_db = sqlite3.connect(target)

    try:
        source_db.backup(backup_db)
        backup_db.commit()
    finally:
        backup_db.close()
        source_db.close()

    return {
        "status":"CREATED",
        "source":str(src),
        "backup":str(target),
        "timestamp":stamp
    }
