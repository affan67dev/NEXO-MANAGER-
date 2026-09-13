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
    """Choose one LLM endpoint; never starts or loads a model."""

    def __init__(self, primary_url: str):
        self.primary_url = primary_url
        self.secondary_url = os.getenv("NEXO_QWEN_URL", "").strip()
        self.enabled = os.getenv("NEXO_QWEN_FALLBACK_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.complexity_chars = _positive_int("NEXO_QWEN_COMPLEXITY_CHARS", DEFAULT_COMPLEXITY_CHARS)

    def _secondary_available(self) -> bool:
        return self.enabled and bool(self.secondary_url) and self.secondary_url != self.primary_url

    def choose_model(self, goal: str, messages: list[dict[str, Any]], intent: str | None = None) -> str:
        """Choose before execution. Length is a signal, never the only signal."""
        text = str(goal or "").strip().lower()
        for message in messages:
            if isinstance(message, dict) and str(message.get("role", "")).lower() == "user":
                content = str(message.get("content", "")).strip().lower()
                if content and content != text:
                    text += "\n" + content

        reasoning_terms = (
            "analyze", "analyse", "reason", "reasoning", "compare", "tradeoff",
            "root cause", "deep dive", "in depth", "step by step", "architecture",
            "design", "debug", "diagnose", "evaluate", "critically", "why does",
            "why is", "multiple possibilities", "pros and cons", "complex", "detailed",
        )
        reasoning_signal = any(term in text for term in reasoning_terms)
        word_count = len(text.split())
        char_count = len(text)
        normalized_intent = (intent or "").strip().lower()
        complex_intent = normalized_intent in {"coding", "database", "monitoring"} and reasoning_signal
        long_signal = char_count >= self.complexity_chars or word_count >= 120

        # If a request is semantically complex/long, it is a Qwen request even when
        # Qwen is unavailable. call() then fails closed instead of silently using LLaMA.
        if reasoning_signal or complex_intent or long_signal:
            return "qwen"
        return "llama"

    def should_use_secondary(self, goal: str, messages: list[dict[str, Any]], intent: str | None = None) -> bool:
        return self.choose_model(goal, messages, intent=intent) == "qwen"

    def call(self, goal: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, ask_fn: Callable[..., dict[str, Any]], *, intent: str | None = None) -> dict[str, Any]:
        """Call one selected model; Qwen is fallback only after a LLaMA failure."""
        selected = self.choose_model(goal, messages, intent=intent)
        if selected == "qwen":
            if not self._secondary_available():
                raise RuntimeError("qwen_not_configured")
            primary = self.secondary_url
        else:
            primary = self.primary_url
            if not primary:
                raise RuntimeError("llama_not_configured")

        try:
            return ask_fn(primary, messages, tools)
        except Exception as exc:
            if selected == "llama" and self._secondary_available():
                try:
                    return ask_fn(self.secondary_url, messages, tools)
                except Exception as fallback_exc:
                    raise RuntimeError(f"llama_failed_then_qwen_failed:{type(exc).__name__}:{type(fallback_exc).__name__}") from fallback_exc
            if selected == "qwen":
                raise RuntimeError(f"qwen_failed:{type(exc).__name__}") from exc
            raise
