from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from core.request_context import RequestContext


@dataclass(frozen=True)
class ChannelResponse:
    answer: str
    action: str = "answer"
    status: str = "ok"
    request_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "answer": self.answer,
            "action": self.action,
            "status": self.status,
        }
        if self.request_id:
            result["request_id"] = self.request_id
        return result


class ChannelAdapter(Protocol):
    """Thin channel boundary; intelligence stays in NEXO core services."""

    channel: str

    def build_context(self, actor_id: str | None, session_id: str | None) -> RequestContext: ...

    def receive(self, payload: dict[str, Any]) -> str: ...

    def send(self, response: ChannelResponse) -> Any: ...
