from __future__ import annotations

import logging
from typing import Any

from services.llm_provider import LLMProvider, create_llm_provider

logger = logging.getLogger("nexo.llm_router")


class LLMRouter:
    """Single provider-selection boundary; provider-specific transport stays in LLMProvider."""

    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or create_llm_provider()

    def choose_model(self, goal: str, messages: list[dict[str, Any]], intent: str | None = None) -> str:
        return self.provider.model

    def should_use_secondary(self, goal: str, messages: list[dict[str, Any]], intent: str | None = None) -> bool:
        return False

    def call(
        self,
        goal: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        ask_fn: Any = None,
        *,
        intent: str | None = None,
    ) -> dict[str, Any]:
        del goal, ask_fn
        max_tokens = int(getattr(getattr(self.provider, "config", None), "output_tokens", 256))
        result = self.provider.complete(messages, tools, max_tokens=max_tokens)
        logger.info("llm_request_success provider=%s model=%s intent=%s", self.provider.name, self.provider.model, intent or "unknown")
        return result
