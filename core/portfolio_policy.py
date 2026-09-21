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
PRIVATE_REQUEST = re.compile(
    r"(?i)\b(privately|private memory|private conversation|private chat|telegram conversation|owner memory|what did affan tell you privately|what did affan tell you in private)\b"
)
TOOL_REQUEST = re.compile(
    r"(?i)\b(run|execute|invoke|call)\b.*\b(shell|command|terminal|filesystem|file|github|openhands|tool)\b|\b(openhands|shell command|arbitrary command|modify github|access filesystem)\b"
)
PORTFOLIO_TERMS = re.compile(
    r"(?i)\b(affan|portfolio|project|projects|omnix|nexo|journey|github|software|ai|artificial intelligence|development|developer|technology|technologies|stack|website|coding|programming|qwen|local ai)\b"
)
TELEGRAM_ONLY = re.compile(
    r"(?i)\b(owner|admin|administrator|private|internal|server|database|logs|runtime|telegram bot|maintenance|system health)\b"
)


def decide(text: str) -> PolicyDecision:
    value = (text or "").strip()
    if not value:
        return PolicyDecision(Action.OUT_OF_SCOPE, "empty_request")
    if SENSITIVE.search(value):
        return PolicyDecision(Action.REFUSED, "sensitive_request")
    if PRIVATE_REQUEST.search(value):
        return PolicyDecision(Action.REDIRECT_TELEGRAM, "private_information_request")
    if TOOL_REQUEST.search(value):
        return PolicyDecision(Action.REFUSED, "public_tools_not_permitted")
    if TELEGRAM_ONLY.search(value) and not PORTFOLIO_TERMS.search(value):
        return PolicyDecision(Action.REDIRECT_TELEGRAM, "non_public_owner_or_runtime_topic")
    if PORTFOLIO_TERMS.search(value):
        return PolicyDecision(Action.ANSWER, "public_portfolio_topic")
    # Harmless general questions may be answered, but callers must not attach
    # portfolio history/knowledge unless the request is actually portfolio-related.
    return PolicyDecision(Action.ANSWER, "general_public_question")


def response(action: Action, answer: str, scope: str = "public_portfolio", *, telegram_url: str | None = None) -> dict[str, str]:
    result = {"answer": (answer or "").strip(), "action": action.value, "scope": scope}
    if action is Action.REDIRECT_TELEGRAM and telegram_url:
        result["telegram_url"] = telegram_url
    return result
