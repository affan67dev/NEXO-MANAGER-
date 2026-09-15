from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

DEFAULT_RETRIES = 1
DEFAULT_BACKOFF_SECONDS = 0.35
logger = logging.getLogger("nexo.llm_router")


def _nonnegative_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default)).strip()))
    except (TypeError, ValueError):
        return default


def _nonnegative_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default)).strip()))
    except (TypeError, ValueError):
        return default


def _valid_response(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return False
    if message.get("tool_calls"):
        return True
    return bool(str(message.get("content") or "").strip()) or bool(str(message.get("reasoning_content") or "").strip())


class LLMRouter:
    """Single-model router: every normal request is sent to the running Qwen server."""

    def __init__(self, qwen_url: str):
        self.qwen_url = (qwen_url or "").strip()
        self.retries = _nonnegative_int("NEXO_LLM_RETRIES", DEFAULT_RETRIES)
        self.backoff = _nonnegative_float("NEXO_LLM_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS)

    def choose_model(self, goal: str, messages: list[dict[str, Any]], intent: str | None = None) -> str:
        return "qwen"

    def should_use_secondary(self, goal: str, messages: list[dict[str, Any]], intent: str | None = None) -> bool:
        return False

    def _attempt(self, messages: list[dict[str, Any]], tools, ask_fn: Callable[..., dict[str, Any]]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                data = ask_fn(self.qwen_url, messages, tools)
                if not _valid_response(data):
                    raise RuntimeError("invalid_model_response")
                if attempt:
                    logger.info("qwen_retry_success attempt=%d", attempt + 1)
                return data
            except Exception as exc:
                last_exc = exc
                logger.warning("qwen_attempt_failed category=%s attempt=%d", type(exc).__name__, attempt + 1)
                if attempt < self.retries and self.backoff:
                    time.sleep(self.backoff * (2 ** attempt))
        raise RuntimeError("qwen_request_failed") from last_exc

    def call(self, goal: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, ask_fn: Callable[..., dict[str, Any]], *, intent: str | None = None) -> dict[str, Any]:
        if not self.qwen_url:
            raise RuntimeError("qwen_endpoint_not_configured")
        result = self._attempt(messages, tools, ask_fn)
        logger.info("qwen_request_success intent=%s", intent or "unknown")
        return result
