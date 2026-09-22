from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class Action(str, Enum):
    ANSWER = "answer"
    OUT_OF_SCOPE = "out_of_scope"
    REDIRECT_TELEGRAM = "redirect_telegram"
    REFUSED = "refused"


@dataclass(frozen=True)
class PolicyDecision:
    action: Action
    reason: str


SENSITIVE = re.compile(
    r"(?i)\b(api[_ -]?key|password|passwd|telegram[_ -]?(?:token|credential)|bot[_ -]?token|private[_ -]?repo|private[_ -]?repository|private[_ -]?database|database[_ -]?(?:password|credential|url)|service[_ -]?role|secret|hidden[_ -]?prompt|system[_ -]?prompt|developer[_ -]?prompt|internal[_ -]?(?:server|security|config|configuration)|private[_ -]?personal)\b"
)
PORTFOLIO_TERMS = re.compile(
    r"(?i)\b(affan|portfolio|project|projects|omnix|nexo|alex|picsync|ajentic(?:-ai-model)?|journey|github|software|ai|artificial intelligence|development|developer|technology|technologies|stack|website|coding|programming|qwen|local ai)\b"
)
PRIVATE_DATA = re.compile(r"(?i)\b(private\w*|secret\w*|hidden\w*|confidential\w*)\b.*\b(telegram|conversation|chat|message|memory|repo|repository|database|file|system)\b|\b(telegram|conversation|chat|message|memory|repo|repository|database|file|system)\b.*\b(private\w*|secret\w*|hidden\w*|confidential\w*)\b")
EXECUTION_REQUEST = re.compile(r"(?i)\b(shell|terminal|command line|execute|run a command|arbitrary code|code execution)\b")
TELEGRAM_ONLY = re.compile(r"(?i)\b(owner|admin|administrator|private|internal|server|database|logs|runtime|telegram bot|maintenance|system health)\b")


def decide(text: str) -> PolicyDecision:
    value = (text or "").strip()
    if not value:
        return PolicyDecision(Action.OUT_OF_SCOPE, "empty_request")
    if SENSITIVE.search(value) or PRIVATE_DATA.search(value) or EXECUTION_REQUEST.search(value):
        return PolicyDecision(Action.REFUSED, "sensitive_request")
    if TELEGRAM_ONLY.search(value) and not PORTFOLIO_TERMS.search(value):
        return PolicyDecision(Action.REDIRECT_TELEGRAM, "non_public_owner_or_runtime_topic")
    if not PORTFOLIO_TERMS.search(value):
        return PolicyDecision(Action.OUT_OF_SCOPE, "not_portfolio_related")
    return PolicyDecision(Action.ANSWER, "public_portfolio_topic")


def response(action: Action, answer: str, scope: str = "public_portfolio", *, telegram_url: str | None = None) -> dict[str, str]:
    result = {"answer": (answer or "").strip(), "action": action.value, "scope": scope}
    if action is Action.REDIRECT_TELEGRAM and telegram_url:
        result["telegram_url"] = telegram_url
    return result
