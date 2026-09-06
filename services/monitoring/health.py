from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

def health_report(checks: dict[str, Any]) -> dict[str, Any]:
    failures = [k for k, v in checks.items() if v is False]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "attention_required" if failures else "healthy",
        "problems": failures,
        "checks": checks,
        "verification": "not_verified" if not checks else "observed"
    }
