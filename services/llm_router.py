from __future__ import annotations

import os
from typing import Any, Callable

DEFAULT_COMPLEXITY_CHARS = 3500


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default)).strip()))
    except (TypeError, ValueError):
        return default


class LLMRouter:
    """Select already-running LLM endpoints; never starts or loads a model."""

    def __init__(self, primary_url: str):
        self.primary_url = primary_url
        self.secondary_url = os.getenv("NEXO_QWEN_URL", "").strip()
        self.enabled = os.getenv("NEXO_QWEN_FALLBACK_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.complexity_chars = _positive_int("NEXO_QWEN_COMPLEXITY_CHARS", DEFAULT_COMPLEXITY_CHARS)

    def _secondary_available(self) -> bool:
        return self.enabled and bool(self.secondary_url) and self.secondary_url != self.primary_url

    def should_use_secondary(self, goal: str, messages: list[dict[str, Any]]) -> bool:
        if not self._secondary_available():
            return False
        total_chars = sum(len(str(m.get("content", ""))) for m in messages if isinstance(m, dict))
        return len(str(goal)) >= self.complexity_chars or total_chars >= self.complexity_chars * 2

    def call(self, goal: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, ask_fn: Callable[..., dict[str, Any]]) -> dict[str, Any]:
        if self.should_use_secondary(goal, messages):
            urls = [self.secondary_url, self.primary_url]
        else:
            urls = [self.primary_url, self.secondary_url]

        last_error: Exception | None = None
        for url in urls:
            if not url or (url == self.secondary_url and not self._secondary_available()):
                continue
            try:
                return ask_fn(url, messages, tools)
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise RuntimeError("no_llm_endpoint_configured")
