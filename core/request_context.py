from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import uuid

from core.identity import resolve_bot_identity

Channel = Literal["portfolio_web", "telegram"]
ActorType = Literal["visitor", "public_client", "admin"]
Scope = Literal["public_portfolio", "telegram_public", "owner_admin"]


@dataclass(frozen=True)
class RequestContext:
    channel: Channel
    actor_type: ActorType
    scope: Scope
    actor_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None

    @classmethod
    def portfolio(cls, session_id: str, request_id: str | None = None) -> "RequestContext":
        return cls("portfolio_web", "visitor", "public_portfolio", None, session_id, request_id or new_request_id())

    @classmethod
    def telegram(cls, user_id: int | str, bot_role: str, request_id: str | None = None) -> "RequestContext":
        identity = resolve_bot_identity(bot_role, user_id)
        scope: Scope = "owner_admin" if identity.is_admin else "telegram_public"
        actor_type: ActorType = "admin" if identity.is_admin else "public_client"
        return cls("telegram", actor_type, scope, identity.telegram_user_id, None, request_id or new_request_id())


def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:16]}"
