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

    def health_check(self, timeout: float = 10.0) -> dict[str, Any]:
        """Check Supabase reachability and public-key acceptance separately.

        The Data API root (/rest/v1/) is intentionally not used here because
        Supabase now restricts its OpenAPI schema endpoint to secret keys.
        The Auth settings endpoint is suitable for validating a configured
        public/anon key without accessing application data or bypassing RLS.
        """

        try:
            response = httpx.get(
                f"{self.url}/auth/v1/settings",
                headers=self.headers,
                timeout=timeout,
            )
        except httpx.RequestError as exc:
            return {
                "status": "network_unreachable",
                "reachable": False,
                "credential_accepted": False,
                "http_status": None,
                "error": exc.__class__.__name__,
            }

        status = response.status_code
        if 200 <= status < 300:
            return {
                "status": "credential_accepted",
                "reachable": True,
                "credential_accepted": True,
                "http_status": status,
            }
        if status == 401:
            return {
                "status": "credential_rejected",
                "reachable": True,
                "credential_accepted": False,
                "http_status": status,
            }
        if status == 403:
            return {
                "status": "endpoint_permission_failure",
                "reachable": True,
                "credential_accepted": False,
                "http_status": status,
            }
        if 400 <= status < 500:
            return {
                "status": "endpoint_failure",
                "reachable": True,
                "credential_accepted": False,
                "http_status": status,
            }
        return {
            "status": "service_failure",
            "reachable": True,
            "credential_accepted": False,
            "http_status": status,
        }

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
