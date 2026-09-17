from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.memory_engine import create_memory_candidate, approve_memory_candidate, reject_memory_candidate, supersede_memory

MEMORY_TYPES = {"temporary_context", "stable_preference", "project_information", "user_fact", "instruction", "correction"}


@dataclass(frozen=True)
class MemoryCandidate:
    user_id: str
    content: str
    category: str
    source: str = "conversation"
    importance: int = 5
    supersedes_id: int | None = None


def validate_candidate(candidate: MemoryCandidate) -> tuple[bool, str]:
    if not candidate.user_id or not candidate.content.strip():
        return False, "missing_memory_identity_or_content"
    if candidate.category not in MEMORY_TYPES:
        return False, "invalid_memory_category"
    if not 1 <= int(candidate.importance) <= 10:
        return False, "invalid_memory_importance"
    return True, "ok"


def propose(candidate: MemoryCandidate) -> int | None:
    valid, _reason = validate_candidate(candidate)
    if not valid:
        return None
    return create_memory_candidate(
        user_id=candidate.user_id,
        category=candidate.category,
        content=candidate.content,
        importance=candidate.importance,
        source=candidate.source,
        supersedes_id=candidate.supersedes_id,
    )


def approve(candidate_id: int) -> bool:
    return approve_memory_candidate(candidate_id)


def reject(candidate_id: int) -> bool:
    return reject_memory_candidate(candidate_id)


def supersede(memory_id: int) -> bool:
    return supersede_memory(memory_id)
