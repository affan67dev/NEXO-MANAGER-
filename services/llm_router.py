from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

DEFAULT_COMPLEXITY_CHARS = 3500
DEFAULT_RETRIES = 1
DEFAULT_BACKOFF_SECONDS = 0.35
logger = logging.getLogger("nexo.llm_router")


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default)).strip()))
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
    return bool(str(message.get("content") or "").strip())


class LLMRouter:
    """Deterministic model selection plus bounded, bidirectional failover."""

    def __init__(self, primary_url: str):
        self.primary_url = (primary_url or "").strip()
        self.secondary_url = os.getenv("NEXO_QWEN_URL", "").strip()
        self.enabled = os.getenv("NEXO_QWEN_FALLBACK_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.complexity_chars = _positive_int("NEXO_QWEN_COMPLEXITY_CHARS", DEFAULT_COMPLEXITY_CHARS)
        self.retries = _positive_int("NEXO_LLM_RETRIES", DEFAULT_RETRIES)
        self.backoff = _nonnegative_float("NEXO_LLM_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS)

    def _secondary_available(self) -> bool:
        return self.enabled and bool(self.secondary_url) and self.secondary_url != self.primary_url

    def choose_model(self, goal: str, messages: list[dict[str, Any]], intent: str | None = None) -> str:
        text = str(goal or "").strip().lower()
        for message in messages:
            if isinstance(message, dict) and str(message.get("role", "")).lower() == "user":
                content = str(message.get("content", "")).strip().lower()
                if content and content != text:
                    text += "\n" + content
        reasoning_terms = (
            "analyze", "analyse", "reason", "reasoning", "compare", "tradeoff", "root cause",
            "deep dive", "in depth", "step by step", "architecture", "design", "debug",
            "diagnose", "evaluate", "critically", "why does", "why is", "multiple possibilities",
            "pros and cons", "complex", "detailed", "advanced mathematics", "structured output",
        )
        reasoning_signal = any(term in text for term in reasoning_terms)
        word_count = len(text.split())
        char_count = len(text)
        normalized_intent = (intent or "").strip().lower()
        complex_intent = normalized_intent in {"coding", "database", "verification", "monitoring"} and (reasoning_signal or word_count >= 60)
        long_signal = char_count >= self.complexity_chars or word_count >= 120
        if reasoning_signal or complex_intent or long_signal:
            return "qwen"
        return "llama"

    def should_use_secondary(self, goal: str, messages: list[dict[str, Any]], intent: str | None = None) -> bool:
        return self.choose_model(goal, messages, intent=intent) == "qwen"

    def _attempt(self, url: str, messages: list[dict[str, Any]], tools, ask_fn: Callable[..., dict[str, Any]], model: str) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                data = ask_fn(url, messages, tools)
                if not _valid_response(data):
                    raise RuntimeError("invalid_model_response")
                if attempt:
                    logger.info("model_retry_success model=%s attempt=%d", model, attempt + 1)
                return data
            except Exception as exc:
                last_exc = exc
                logger.warning("model_attempt_failed model=%s category=%s attempt=%d", model, type(exc).__name__, attempt + 1)
                if attempt < self.retries and self.backoff:
                    time.sleep(self.backoff * (2 ** attempt))
        raise RuntimeError("model_attempt_failed") from last_exc

    def call(self, goal: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, ask_fn: Callable[..., dict[str, Any]], *, intent: str | None = None) -> dict[str, Any]:
        preferred = self.choose_model(goal, messages, intent=intent)
        if preferred == "qwen" and self._secondary_available():
            order = [(self.secondary_url, "qwen"), (self.primary_url, "llama")]
        else:
            order = [(self.primary_url, "llama")]
            if self._secondary_available():
                order.append((self.secondary_url, "qwen"))
        errors: list[str] = []
        for url, model in order:
            if not url:
                continue
            try:
                result = self._attempt(url, messages, tools, ask_fn, model)
                logger.info("model_request_success model=%s", model)
                return result
            except Exception as exc:
                errors.append(type(exc).__name__)
                logger.warning("model_failover model=%s category=%s", model, type(exc).__name__)
        logger.error("all_models_failed attempts=%d categories=%s", len(errors), ",".join(errors))
        raise RuntimeError("all_models_failed")
