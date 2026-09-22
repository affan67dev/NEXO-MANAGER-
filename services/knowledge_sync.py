from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.portfolio_store import upsert_knowledge


@dataclass(frozen=True)
class ApprovedSource:
    source: str
    repository: str
    file_path: str
    project: str
    visibility: str = "public"


@dataclass(frozen=True)
class KnowledgeCandidate:
    repository: str
    file_path: str
    project: str
    content: str
    version_sha: str


class KnowledgeSync:
    """Ingestion boundary for explicitly approved public sources.

    Network/GitHub fetching is intentionally not performed here. A future sync job
    should fetch only allowlisted resources and pass verified content to sync().
    """

    def __init__(self, approved: Iterable[ApprovedSource] = ()) -> None:
        self.approved = {(x.repository, x.file_path): x for x in approved if x.visibility == "public"}

    def _validate_candidate(self, candidate: KnowledgeCandidate) -> None:
        if not candidate.repository or not candidate.file_path or not candidate.version_sha:
            raise ValueError("knowledge_candidate_identity_invalid")
        if not candidate.content.strip():
            raise ValueError("knowledge_candidate_empty")
        if len(candidate.content) > 100000:
            raise ValueError("knowledge_candidate_too_large")

    def sync(self, repository: str, file_path: str, content: str, version_sha: str) -> int:
        source = self.approved.get((repository, file_path))
        if source is None:
            raise PermissionError("knowledge_source_not_allowlisted")
        candidate = KnowledgeCandidate(repository, file_path, source.project, str(content or ""), version_sha)
        self._validate_candidate(candidate)
        return upsert_knowledge(
            source=source.source,
            repository=repository,
            file_path=file_path,
            project=source.project,
            content=candidate.content,
            visibility="public",
            version_sha=version_sha,
            indexed=True,
        )
