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
    """Choose one already-running LLM endpoint; never starts or loads a model."""

    def __init__(self, primary_url: str):
        self.primary_url = primary_url
        self.secondary_url = os.getenv("NEXO_QWEN_URL", "").strip()
        self.enabled = os.getenv("NEXO_QWEN_FALLBACK_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.complexity_chars = _positive_int("NEXO_QWEN_COMPLEXITY_CHARS", DEFAULT_COMPLEXITY_CHARS)

    def _secondary_available(self) -> bool:
        return self.enabled and bool(self.secondary_url) and self.secondary_url != self.primary_url

    def choose_model(self, goal: str, messages: list[dict[str, Any]], intent: str | None = None) -> str:
        """Route before any model call.

        Intent/semantic signals have priority over length. Length is only a secondary
        signal for genuinely long requests. A complex request never calls LLaMA first.
        """
        normalized_intent = (intent or "").strip().lower()
        if normalized_intent in {"security", "conversation", "support", "verification", "device_control"}:
            # These may still be complex, so use explicit reasoning signals below.
            pass
        if normalized_intent in {"coding", "database", "monitoring"}:
            # Operational tasks are allowed to use Qwen when their wording indicates
            # substantial reasoning; otherwise LLaMA remains the fast first model.
            pass

        text = " ".join([
            str(goal or ""),
            " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict)),
        ]).lower()
        reasoning_terms = (
            "analyze", "analyse", "reason", "reasoning", "compare", "tradeoff",
            "root cause", "deep dive", "in depth", "step by step", "architecture",
            "design", "debug", "diagnose", "evaluate", "critically", "why does",
            "why is", "multiple possibilities", "pros and cons", "complex", "detailed",
        )
        reasoning_signal = any(term in text for term in reasoning_terms)
        word_count = len(str(goal or "").split())
        char_count = len(str(goal or ""))
        long_signal = char_count >= self.complexity_chars or word_count >= 120

        if self._secondary_available() and (reasoning_signal or long_signal):
            return "qwen"
        return "llama"

    def should_use_secondary(self, goal: str, messages: list[dict[str, Any]], intent: str | None = None) -> bool:
        return self.choose_model(goal, messages, intent=intent) == "qwen"

    def call(
        self,
        goal: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        ask_fn: Callable[..., dict[str, Any]],
        *,
        intent: str | None = None,
    ) -> dict[str, Any]:
        """Call the selected model only.

        If LLaMA fails, Qwen is a safe secondary fallback when explicitly enabled.
        If Qwen was selected and fails, do not silently downgrade to LLaMA: surface the
        failure so the caller cannot return a misleading answer from the wrong model.
        """
        selected = self.choose_model(goal, messages, intent=intent)
        primary = self.primary_url if selected == "llama" else self.secondary_url
        if not primary:
            raise RuntimeError("qwen_not_configured" if selected == "qwen" else "llama_not_configured")

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
