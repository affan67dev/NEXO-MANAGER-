from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _inside_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
        return resolved == ROOT or ROOT in resolved.parents
    except OSError:
        return False


def backup_sqlite(source: str, destination_dir: str = "data/backups") -> dict:
    try:
        src_raw = Path(source).expanduser()
        src = (ROOT / src_raw).resolve() if not src_raw.is_absolute() else src_raw.resolve()
        out_raw = Path(destination_dir).expanduser()
        out_dir = (ROOT / out_raw).resolve() if not out_raw.is_absolute() else out_raw.resolve()
    except (OSError, RuntimeError):
        return {"status": "NOT_CREATED", "reason": "invalid_path"}

    if not _inside_root(src) or not _inside_root(out_dir):
        return {"status": "NOT_CREATED", "reason": "path_not_allowed"}
    if not src.is_file() or src.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        return {"status": "NOT_CREATED", "reason": "database_missing_or_invalid"}

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = out_dir / f"database_{stamp}.sqlite"
        with sqlite3.connect(src, timeout=10) as source_db, sqlite3.connect(target, timeout=10) as backup_db:
            source_db.backup(backup_db)
        return {"status": "CREATED", "source": str(src), "backup": str(target), "timestamp": stamp}
    except (OSError, sqlite3.Error):
        return {"status": "NOT_CREATED", "reason": "backup_failed"}
