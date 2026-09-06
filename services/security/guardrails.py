from __future__ import annotations
import re

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+")
]

BLOCKED_ACTIONS = {
    "production_deploy",
    "permanent_delete",
    "irreversible_database_change",
    "financial_transaction",
    "credential_exfiltration"
}

def inspect(text: str, action: str | None = None) -> dict:
    secrets = [p.pattern for p in SECRET_PATTERNS if p.search(text)]
    blocked = action in BLOCKED_ACTIONS
    return {
        "safe": not secrets and not blocked,
        "secret_signals": secrets,
        "blocked_action": blocked,
        "status": "BLOCKED" if secrets or blocked else "ALLOWED_FOR_REVIEW"
    }
