from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Channel = Literal["portfolio_web", "telegram", "email", "whatsapp", "mobile_app", "social"]
ActorType = Literal["visitor", "telegram_user", "owner"]
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
        return cls("portfolio_web", "visitor", "public_portfolio", None, session_id, request_id)

    @classmethod
    def telegram(cls, user_id: int | str, owner: bool, request_id: str | None = None) -> "RequestContext":
        uid = str(user_id)
        if owner:
            return cls("telegram", "owner", "owner_admin", uid, None, request_id)
        return cls("telegram", "telegram_user", "telegram_public", uid, None, request_id)
