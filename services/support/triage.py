from __future__ import annotations

HIGH_RISK = (
    "payment","refund","charged","security","breach","account takeover",
    "data loss","legal","fraud","unauthorized"
)

def triage(message: str) -> dict:
    text = message.lower()
    critical = [x for x in HIGH_RISK if x in text]
    if critical:
        priority = "HIGH"
        action = "ESCALATE_FOR_OWNER_REVIEW"
    elif any(x in text for x in ("bug","error","crash","not working")):
        priority = "MEDIUM"
        action = "CREATE_TECHNICAL_TICKET"
    else:
        priority = "NORMAL"
        action = "PREPARE_RESPONSE"
    return {
        "priority":priority,
        "matched_signals":critical,
        "action":action,
        "message":message
    }
