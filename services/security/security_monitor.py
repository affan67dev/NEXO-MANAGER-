from __future__ import annotations
import re

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\\s*[:=]\\s*\\S+"),
    re.compile(r"\\b\\d{4}[- ]?\\d{4}[- ]?\\d{4}[- ]?\\d{4}\\b")
]

def scan_text(text: str) -> dict:
    findings = [p.pattern for p in SECRET_PATTERNS if p.search(text)]
    return {
        "safe": not findings,
        "findings": findings,
        "action": "redact_and_escalate" if findings else "none"
    }
