from __future__ import annotations

import re
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "telegram.log"
ERROR_RE = re.compile(r"(?i)(traceback|exception|error|failed|invalidtoken)")


def recent_errors(lines: int = 80) -> list[str]:
    if not LOG.exists():
        return []
    try:
        rows = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(lines)):]
        return [line[:500] for line in rows if ERROR_RE.search(line)]
    except OSError:
        return []


def health_report() -> dict:
    errors = recent_errors()
    return {"ok": not errors, "error_count": len(errors), "errors": errors[-20:]}
