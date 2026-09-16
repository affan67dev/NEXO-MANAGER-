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


class KnowledgeSync:
    """Small ingestion boundary for explicitly approved public sources.

    Network/GitHub fetching is intentionally not performed here. A future sync job
    should fetch only allowlisted resources and pass verified content to sync().
    """

    def __init__(self, approved: Iterable[ApprovedSource] = ()) -> None:
        self.approved = {(x.repository, x.file_path): x for x in approved if x.visibility == "public"}

    def sync(self, repository: str, file_path: str, content: str, version_sha: str) -> int:
        source = self.approved.get((repository, file_path))
        if source is None:
            raise PermissionError("knowledge_source_not_allowlisted")
        return upsert_knowledge(
            source=source.source,
            repository=repository,
            file_path=file_path,
            project=source.project,
            content=content,
            visibility="public",
            version_sha=version_sha,
            indexed=True,
        )
