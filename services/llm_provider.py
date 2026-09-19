from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import os
import time
from typing import Any, Protocol

import httpx

logger = logging.getLogger("nexo.llm_provider")


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 256,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float
    retries: int
    backoff_seconds: float
    context_tokens: int
    output_tokens: int
    fallback_models: tuple[str, ...] = ()
    max_retry_after_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = os.getenv("LLM_PROVIDER", "").strip().lower()
        api_key = os.getenv("LLM_API_KEY", "").strip()
        model = os.getenv("LLM_MODEL", "").strip()
        base_url = os.getenv("LLM_BASE_URL", "").strip()
        if not provider:
            raise RuntimeError("llm_provider_not_configured")
        if provider != "openrouter":
            raise RuntimeError("unsupported_llm_provider")
        if not api_key:
            raise RuntimeError("llm_api_key_not_configured")
        if not model:
            raise RuntimeError("llm_model_not_configured")
        if not base_url:
            raise RuntimeError("llm_base_url_not_configured")
        fallback_models = tuple(
            item for item in (x.strip() for x in os.getenv("LLM_FALLBACK_MODELS", "").split(","))
            if item and item != model
        )
        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=_float_env("LLM_TIMEOUT_SECONDS", 30.0, 1.0, 120.0),
            retries=_int_env("LLM_RETRIES", 1, 0, 3),
            backoff_seconds=_float_env("LLM_BACKOFF_SECONDS", 0.5, 0.0, 10.0),
            context_tokens=_int_env("LLM_CONTEXT_TOKENS", 4096, 512, 32768),
            output_tokens=_int_env("LLM_OUTPUT_TOKENS", 512, 128, 4096),
            fallback_models=fallback_models[:3],
            max_retry_after_seconds=_float_env("LLM_MAX_RETRY_AFTER_SECONDS", 60.0, 0.0, 120.0),
        )


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(max(int(os.getenv(name, str(default)).strip()), minimum), maximum)
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        return min(max(float(os.getenv(name, str(default)).strip()), minimum), maximum)
    except (TypeError, ValueError):
        return default


def _endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    return value if value.endswith("/chat/completions") else value + "/chat/completions"


def _retry_after_seconds(response: httpx.Response, maximum: float) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return min(max(0.0, delay), maximum)


def validate_provider_response(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return False
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return False
    return bool(message.get("tool_calls")) or bool(str(message.get("content") or "").strip())


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, config: LLMConfig | None = None, client: httpx.Client | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        if self.config.provider != self.name:
            raise RuntimeError("unsupported_llm_provider")
        self.model = self.config.model
        self._client = client
        self._owns_client = client is None

    def _payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, max_tokens: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.15,
            "max_tokens": max(1, min(int(max_tokens), self.config.output_tokens)),
            "stream": False,
        }
        if self.config.fallback_models:
            payload["models"] = [self.config.model, *self.config.fallback_models]
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, max_tokens: int = 256) -> dict[str, Any]:
        payload = self._payload(messages, tools, max_tokens)
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        client = self._client or httpx.Client(timeout=self.config.timeout_seconds)
        try:
            for attempt in range(self.config.retries + 1):
                started = time.monotonic()
                try:
                    response = client.post(_endpoint(self.config.base_url), headers=headers, json=payload)
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        category = f"http_{response.status_code}"
                        logger.warning("llm_provider_failure provider=%s model=%s category=%s attempt=%d latency_ms=%d", self.name, self.model, category, attempt + 1, elapsed_ms)
                        if attempt < self.config.retries:
                            delay = self.config.backoff_seconds * (2 ** attempt)
                            if response.status_code == 429:
                                retry_after = _retry_after_seconds(response, self.config.max_retry_after_seconds)
                                if retry_after is not None:
                                    delay = retry_after
                            time.sleep(delay)
                            continue
                        raise RuntimeError("llm_provider_unavailable")
                    if response.status_code in {401, 403}:
                        logger.error("llm_provider_failure provider=%s model=%s category=authorization latency_ms=%d", self.name, self.model, elapsed_ms)
                        raise RuntimeError("llm_provider_authorization_failed")
                    if response.status_code == 404:
                        logger.error("llm_provider_failure provider=%s model=%s category=unavailable_model latency_ms=%d", self.name, self.model, elapsed_ms)
                        raise RuntimeError("llm_model_unavailable")
                    if response.status_code >= 400:
                        logger.warning("llm_provider_failure provider=%s model=%s category=http_%d latency_ms=%d", self.name, self.model, response.status_code, elapsed_ms)
                        raise RuntimeError("llm_provider_request_failed")
                    try:
                        data = response.json()
                    except (ValueError, json.JSONDecodeError) as exc:
                        raise RuntimeError("llm_provider_malformed_response") from exc
                    if not validate_provider_response(data):
                        raise RuntimeError("llm_provider_malformed_response")
                    logger.info("llm_provider_success provider=%s model=%s latency_ms=%d retry_count=%d", self.name, self.model, elapsed_ms, attempt)
                    return data
                except httpx.TimeoutException as exc:
                    logger.warning("llm_provider_failure provider=%s model=%s category=timeout attempt=%d", self.name, self.model, attempt + 1)
                    if attempt < self.config.retries:
                        time.sleep(self.config.backoff_seconds * (2 ** attempt))
                        continue
                    raise RuntimeError("llm_provider_timeout") from exc
                except httpx.RequestError as exc:
                    logger.warning("llm_provider_failure provider=%s model=%s category=network attempt=%d", self.name, self.model, attempt + 1)
                    if attempt < self.config.retries:
                        time.sleep(self.config.backoff_seconds * (2 ** attempt))
                        continue
                    raise RuntimeError("llm_provider_network_failure") from exc
            raise RuntimeError("llm_provider_unavailable")
        finally:
            if self._owns_client:
                client.close()


def create_llm_provider() -> LLMProvider:
    config = LLMConfig.from_env()
    return OpenRouterProvider(config)
