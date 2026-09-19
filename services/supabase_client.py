from __future__ import annotations

import os
from typing import Any

import httpx


class SupabaseClient:
    """Small REST client for NEXO's Supabase project.

    Uses httpx already required by NEXO, so this does not add the
    supabase-py dependency (which would add heavier native build
    requirements on Termux).
    """

    def __init__(self) -> None:
        self.url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        self.anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
        if not self.url:
            raise RuntimeError("supabase_url_not_configured")
        if not self.anon_key:
            raise RuntimeError("supabase_anon_key_not_configured")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "Content-Type": "application/json",
        }

    def health_check(self) -> bool:
        response = httpx.get(
            f"{self.url}/rest/v1/",
            headers=self.headers,
            timeout=10.0,
        )
        return response.status_code < 400

    def select(
        self,
        table: str,
        *,
        query: str = "",
        timeout: float = 10.0,
    ) -> list[dict[str, Any]]:
        response = httpx.get(
            f"{self.url}/rest/v1/{table}",
            params=query,
            headers=self.headers,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError("supabase_invalid_response")
        return data
