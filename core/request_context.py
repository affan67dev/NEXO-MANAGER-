from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.identity import resolve_telegram_identity

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

    @classmethod
    def portfolio(cls, session_id: str) -> "RequestContext":
        return cls("portfolio_web", "visitor", "public_portfolio", None, session_id)

    @classmethod
    def telegram(cls, user_id: int | str) -> "RequestContext":
        identity = resolve_telegram_identity(user_id)
        if identity.is_admin:
            return cls("telegram", "admin", "owner_admin", identity.telegram_user_id, None)
        return cls("telegram", "public_client", "telegram_public", identity.telegram_user_id, None)
