from __future__ import annotations

import re

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|otp)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]+"),
    re.compile(r"(?i)-----BEGIN(?: [A-Z]+)* PRIVATE KEY-----"),
    re.compile(r"(?i)\b(card[_ -]?number|authorization)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:sk|rk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\b(?:ghp_|github_pat_|gsk_|AIza)[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
]

BLOCKED_ACTIONS = {
    "production_deploy",
    "permanent_delete",
    "irreversible_database_change",
    "financial_transaction",
    "credential_exfiltration",
    "security_bypass",
}


def inspect(text: str, action: str | None = None) -> dict:
    value = text if isinstance(text, str) else ""
    secrets = [p.pattern for p in SECRET_PATTERNS if p.search(value)]
    blocked = action in BLOCKED_ACTIONS
    return {
        "safe": not secrets and not blocked,
        "secret_signals": secrets,
        "blocked_action": blocked,
        "status": "BLOCKED" if secrets or blocked else "ALLOWED_FOR_REVIEW",
    }
