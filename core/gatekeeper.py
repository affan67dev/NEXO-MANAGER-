import re

MAX_MESSAGE_LENGTH = 10000
SPAM_PATTERNS = (
    r"free\s+money",
    r"click\s+here",
    r"winner",
    r"urgent\s+prize",
    r"claim\s+your\s+reward",
    r"crypto\s+giveaway",
)


def inspect(text: str) -> dict:
    if not isinstance(text, str):
        return {"allow": False, "reason": "invalid_input"}
    value = text.strip()
    if not value:
        return {"allow": False, "reason": "empty"}
    if len(value) > MAX_MESSAGE_LENGTH:
        return {"allow": False, "reason": "message_too_large"}
    hits = [p for p in SPAM_PATTERNS if re.search(p, value, re.I)]
    if hits:
        return {"allow": False, "reason": "possible_spam", "matches": hits}
    return {"allow": True, "reason": "accepted"}
