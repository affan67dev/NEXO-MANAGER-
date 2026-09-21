from __future__ import annotations

import json
import math
import os
from typing import Any

DEFAULT_CONTEXT_TOKENS = 4096
DEFAULT_OUTPUT_TOKENS = 512


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(max(int(os.getenv(name, str(default)).strip()), minimum), maximum)
    except (TypeError, ValueError):
        return default


def context_tokens() -> int:
    return _bounded_int("LLM_CONTEXT_TOKENS", DEFAULT_CONTEXT_TOKENS, 512, 32768)


def output_tokens() -> int:
    return _bounded_int("LLM_OUTPUT_TOKENS", DEFAULT_OUTPUT_TOKENS, 128, 4096)


def input_budget() -> int:
    return max(128, context_tokens() - output_tokens())


def count_input_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> int:
    """Bounded local estimate; no dependency on a local model tokenizer endpoint."""
    payload = json.dumps({"messages": messages, "tools": tools or []}, ensure_ascii=False, separators=(",", ":"))
    return math.ceil(len(payload) / 2)


def fit_messages(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    budget: int | None = None,
) -> list[dict[str, Any]]:
    """Fit deterministic context while preserving the current user request intact."""
    if not messages:
        raise RuntimeError("context_budget_empty")
    system = messages[0] if messages[0].get("role") == "system" else None
    user_indexes = [i for i, item in enumerate(messages) if item.get("role") == "user"]
    if not user_indexes:
        raise RuntimeError("context_budget_missing_user")
    current_index = user_indexes[-1]
    current_user = messages[current_index]
    preserved = [system] if system else []
    if system is not None and not str(system.get("content") or "").strip():
        raise RuntimeError("context_budget_empty_system")

    limit = input_budget() if budget is None else max(128, int(budget))
    mandatory = ([system] if system else []) + [current_user]
    if count_input_tokens(mandatory, tools) > limit:
        raise RuntimeError("context_budget_insufficient")
    # Only the first system message and current user request are mandatory.
    # Auxiliary context, history, and tool results can be discarded deterministically.
    candidates = [item for i, item in enumerate(messages) if i not in {0, current_index}]
    selected: list[dict[str, Any]] = []
    # Callers order optional context by priority. Preserve that order while fitting:
    # recent/relevant conversation -> memory -> authorized knowledge -> older context.
    # The current request and core system prompt are never candidates for dropping.
    for item in candidates:
        trial = preserved + selected + [item, current_user]
        if count_input_tokens(trial, tools) <= limit:
            selected.append(item)
    fitted = preserved + selected + [current_user]
    return fitted
