from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Channel = Literal["portfolio_web", "telegram"]
ActorType = Literal["visitor", "telegram_user", "owner"]
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
    def telegram(cls, user_id: int | str, owner: bool) -> "RequestContext":
        uid = str(user_id)
        if owner:
            return cls("telegram", "owner", "owner_admin", uid, None)
        return cls("telegram", "telegram_user", "telegram_public", uid, None)
