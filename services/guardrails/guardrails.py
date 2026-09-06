import re

SECRET_PATTERNS=[
r"\b\d{6}\b",
r"\b(?:api[_ -]?key|token|password|secret)\b",
r"\b(?:otp|cvv|pin)\b"
]

def contains_secret(text):
    return any(re.search(p,text,re.I) for p in SECRET_PATTERNS)

def verify(draft,known_context="",rules=None):
    rules=rules or []
    problems=[]
    if not draft or not draft.strip():
        problems.append("EMPTY_RESPONSE")
    if contains_secret(draft):
        problems.append("POSSIBLE_SECRET")
    for rule in rules:
        if rule.lower() not in draft.lower():
            problems.append("RULE_MISSING:"+rule)
    return {"approved":not problems,"problems":problems,"draft":draft}
