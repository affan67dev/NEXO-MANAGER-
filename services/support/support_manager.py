from __future__ import annotations

def classify_support(message: str) -> str:
    t = message.lower()
    if any(x in t for x in ("login", "password", "otp", "account")):
        return "account"
    if any(x in t for x in ("bug", "error", "crash", "not working")):
        return "technical"
    if any(x in t for x in ("report", "abuse", "spam", "harassment")):
        return "moderation"
    return "general"

def prepare_response(message: str, known_context: str = "") -> dict:
    return {
        "category": classify_support(message),
        "message": message,
        "context_used": bool(known_context),
        "send_status": "approval_required"
    }
