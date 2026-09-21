from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Role = Literal["public_client", "admin"]
BotRole = Literal["public", "admin"]


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_user_id: str
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def configured_admin_id() -> str | None:
    value = os.getenv("ADMIN_TELEGRAM_USER_ID", "").strip()
    if not value:
        value = os.getenv("NEXO_OWNER_TELEGRAM_USER_ID", "").strip()
    return value if value.isdigit() else None


def resolve_telegram_identity(user_id: int | str | None) -> TelegramIdentity:
    telegram_user_id = str(user_id).strip() if user_id is not None else ""
    if not telegram_user_id.isdigit():
        raise ValueError("invalid_telegram_user_id")
    role: Role = "admin" if telegram_user_id == configured_admin_id() else "public_client"
    return TelegramIdentity(telegram_user_id=telegram_user_id, role=role)


def resolve_bot_identity(bot_role: BotRole, user_id: int | str | None) -> TelegramIdentity:
    identity = resolve_telegram_identity(user_id)
    if bot_role == "public":
        return TelegramIdentity(identity.telegram_user_id, "public_client")
    if bot_role == "admin":
        if not identity.is_admin:
            raise PermissionError("unauthorized_admin_bot")
        return identity
    raise ValueError("invalid_bot_role")


def authorize_bot_update(bot_role: BotRole, user_id: int | str | None) -> bool:
    try:
        resolve_bot_identity(bot_role, user_id)
    except (PermissionError, ValueError):
        return False
    return True
