from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from core.portfolio_store import upsert_knowledge

GITHUB_API = "https://api.github.com"
OWNER = "affan67dev"
DEFAULT_REPOSITORIES = (
    "affan67dev",
    "NEXO-MANAGER-",
    "OMNIX",
    "PicSyncApp",
    "ajentic-AI-model",
)
DEFAULT_TIMEOUT = 10.0
MAX_README_CHARS = 50000
CHUNK_CHARS = 5000
CHUNK_OVERLAP = 400

SENSITIVE_LINE = re.compile(
    r"(?i)(telegram_bot_token|llm_api_key|api[_ -]?key|password|passwd|secret|authorization|bearer|private[_ -]?(?:key|repo|repository|database)|service[_ -]?role)"
)


@dataclass(frozen=True)
class PublicGitHubSource:
    repository: str
    title: str


def configured_sources() -> tuple[PublicGitHubSource, ...]:
    raw = os.getenv("NEXO_PUBLIC_GITHUB_REPOSITORIES", "").strip()
    names = tuple(x.strip() for x in raw.split(",") if x.strip()) if raw else DEFAULT_REPOSITORIES
    result: list[PublicGitHubSource] = []
    seen: set[str] = set()
    for name in names:
        if "/" in name:
            owner, repo = name.split("/", 1)
            if owner != OWNER:
                continue
        else:
            repo = name
        if not repo or repo in seen:
            continue
        seen.add(repo)
        result.append(PublicGitHubSource(repo, repo))
    return tuple(result)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_text(content: str) -> str:
    lines = [line for line in str(content or "").splitlines() if not SENSITIVE_LINE.search(line)]
    value = "\n".join(lines).strip()
    if len(value) > MAX_README_CHARS:
        value = value[:MAX_README_CHARS].rsplit("\n", 1)[0]
    return value


def _chunks(content: str) -> list[str]:
    value = content.strip()
    if not value:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(value):
        end = min(len(value), start + CHUNK_CHARS)
        chunk = value[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(value):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)
    return chunks


def _readme_url(repository: str) -> str:
    return f"https://github.com/{OWNER}/{repository}/blob/main/README.md"


class PublicKnowledgeRefresher:
    """Fetch only explicitly allowlisted public GitHub READMEs."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            base_url=GITHUB_API,
            timeout=DEFAULT_TIMEOUT,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "ALEX-public-knowledge-sync",
            },
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _fetch_readme(self, repository: str) -> dict[str, Any]:
        response = self.client.get(f"/repos/{OWNER}/{repository}/readme")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("github_invalid_readme_response")
        if data.get("type") != "file" or str(data.get("name", "")).lower() != "readme.md":
            raise RuntimeError("github_readme_not_file")
        return data

    def refresh(self, *, force: bool = False) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        try:
            for source in configured_sources():
                try:
                    data = self._fetch_readme(source.repository)
                    encoded = data.get("content", "")
                    if not encoded:
                        results.append({"repository": source.repository, "status": "empty"})
                        continue
                    raw = base64.b64decode(str(encoded).replace("\n", "")).decode("utf-8", "replace")
                    content = _public_text(raw)
                    if not content:
                        results.append({"repository": source.repository, "status": "filtered"})
                        continue

                    version_sha = str(data.get("sha") or hashlib.sha256(content.encode()).hexdigest())
                    chunks = _chunks(content)
                    inserted = 0
                    for index, chunk in enumerate(chunks, start=1):
                        chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                        upsert_knowledge(
                            source="github_readme",
                            source_type="github_readme",
                            repository=f"{OWNER}/{source.repository}",
                            file_path=f"README.md#chunk-{index:03d}",
                            project=source.title,
                            title=source.title,
                            source_url=_readme_url(source.repository),
                            scope="public_portfolio",
                            content=chunk,
                            visibility="public",
                            version_sha=version_sha,
                            content_hash=chunk_hash,
                            last_ingested_at=_now(),
                            indexed=True,
                        )
                        inserted += 1
                    results.append({
                        "repository": source.repository,
                        "status": "refreshed" if inserted else "empty",
                        "version_sha": version_sha,
                        "chunks": inserted,
                    })
                except (httpx.HTTPError, UnicodeError, ValueError, RuntimeError) as exc:
                    results.append({
                        "repository": source.repository,
                        "status": "error",
                        "error": exc.__class__.__name__,
                    })
            return {"ok": True, "sources": results}
        finally:
            if self._owns_client:
                self.close()


def refresh_public_knowledge(*, force: bool = False) -> dict[str, Any]:
    return PublicKnowledgeRefresher().refresh(force=force)
