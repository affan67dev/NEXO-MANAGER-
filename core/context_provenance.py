from __future__ import annotations

from typing import Literal

ContextSource = Literal[
    "SYSTEM_POLICY",
    "TRUSTED_KNOWLEDGE",
    "APPROVED_MEMORY",
    "SESSION_HISTORY",
    "USER_INPUT",
    "TOOL_RESULT",
    "UNTRUSTED_EXTERNAL_CONTENT",
]

SYSTEM_POLICY = "SYSTEM_POLICY"
TRUSTED_KNOWLEDGE = "TRUSTED_KNOWLEDGE"
APPROVED_MEMORY = "APPROVED_MEMORY"
SESSION_HISTORY = "SESSION_HISTORY"
USER_INPUT = "USER_INPUT"
TOOL_RESULT = "TOOL_RESULT"
UNTRUSTED_EXTERNAL_CONTENT = "UNTRUSTED_EXTERNAL_CONTENT"


def label(source: ContextSource, content: str) -> str:
    """Make provenance explicit without granting retrieved content system authority."""
    return f"[{source}]\n{content or ''}".strip()
