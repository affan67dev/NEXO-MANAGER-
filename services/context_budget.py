from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_CONTEXT_TOKENS = 1024
DEFAULT_OUTPUT_TOKENS = 256
TOKEN_COUNT_TIMEOUT_SECONDS = 5.0


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(max(int(os.getenv(name, str(default)).strip()), minimum), maximum)
    except (TypeError, ValueError):
        return default


def context_tokens() -> int:
    return _bounded_int("NEXO_QWEN_CONTEXT_TOKENS", DEFAULT_CONTEXT_TOKENS, 512, 8192)


def output_tokens() -> int:
    return _bounded_int("NEXO_QWEN_OUTPUT_TOKENS", DEFAULT_OUTPUT_TOKENS, 128, 512)


def input_budget() -> int:
    return max(128, context_tokens() - output_tokens())


def _tokenize_endpoint(chat_url: str) -> str:
    marker = "/v1/chat/completions"
    if marker in chat_url:
        return chat_url.split(marker, 1)[0] + marker + "/input_tokens"
    return chat_url.rstrip("/") + "/input_tokens"


def _estimate_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> int:
    """Conservative fallback when llama.cpp's exact token counter is unavailable."""
    payload = json.dumps({"messages": messages, "tools": tools or []}, ensure_ascii=False, separators=(",", ":"))
    return math.ceil(len(payload) / 2)


def count_input_tokens(chat_url: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> int:
    payload: dict[str, Any] = {"messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    request = urllib.request.Request(
        _tokenize_endpoint(chat_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TOKEN_COUNT_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
        value = data.get("input_tokens")
        if isinstance(value, int) and value >= 0:
            return value
        raise ValueError("invalid_input_token_count")
    except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError):
        return _estimate_tokens(messages, tools)


def fit_messages(
    chat_url: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    budget: int | None = None,
) -> list[dict[str, Any]]:
    """Keep system and current user content intact while deterministically dropping oldest context."""
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
    candidates = [item for i, item in enumerate(messages[1:], start=1) if i != current_index]
    selected: list[dict[str, Any]] = []
    for item in reversed(candidates):
        trial = preserved + [item] + selected + [current_user]
        if count_input_tokens(chat_url, trial, tools) <= limit:
            selected.insert(0, item)
    fitted = preserved + selected + [current_user]
    if count_input_tokens(chat_url, fitted, tools) > limit:
        raise RuntimeError("context_budget_exceeded_user_message_too_large")
    return fitted
