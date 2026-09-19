from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ChannelMessage:
    channel: str
    sender: str
    text: str
    message_id: str | None = None
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


@dataclass(frozen=True)
class ChannelReply:
    channel: str
    recipient: str
    text: str
    request_id: str | None = None


class ChannelGateway:
    """Single channel boundary into the existing ALEX core.

    Adapters normalize provider payloads into ChannelMessage. The supplied
    handler owns ALEX understanding/planning/security/execution; channel code
    contains no business logic.
    """

    def __init__(self, handler: Callable[[ChannelMessage], str]) -> None:
        self.handler = handler

    def handle(self, message: ChannelMessage) -> ChannelReply:
        text = self.handler(message)
        return ChannelReply(
            channel=message.channel,
            recipient=message.sender,
            text=str(text),
            request_id=message.message_id,
        )
