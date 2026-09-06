from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone

ERROR_WORDS = ("error","exception","traceback","fatal","crash","failed","warning")

def scan_log_file(path: str, max_bytes: int = 2_000_000) -> dict:
    p = Path(path)
    if not p.exists():
        return {"status":"missing","file":str(p),"matches":[]}
    text = p.read_text(errors="replace")[-max_bytes:]
    lines = [line for line in text.splitlines() if any(w in line.lower() for w in ERROR_WORDS)]
    return {
        "status":"scanned",
        "file":str(p),
        "timestamp":datetime.now(timezone.utc).isoformat(),
        "matches":lines[-200:],
        "count":len(lines)
    }
