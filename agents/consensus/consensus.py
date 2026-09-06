from __future__ import annotations
from dataclasses import dataclass, asdict

@dataclass
class Review:
    model: str
    decision: str
    evidence: list[str]

def evaluate(reviews: list[Review], high_risk: bool = False) -> dict:
    decisions = [r.decision.upper() for r in reviews]
    failed = [r for r in reviews if r.decision.upper() == "FAIL"]

    if failed:
        return {"status": "BLOCKED", "reason": "review_failed", "reviews": [asdict(r) for r in reviews]}

    if high_risk and len(reviews) < 2:
        return {"status": "BLOCKED", "reason": "insufficient_independent_reviews"}

    if decisions and all(d in ("PASS", "PASS_WITH_WARNINGS") for d in decisions):
        return {"status": "READY_FOR_OWNER_APPROVAL", "reviews": [asdict(r) for r in reviews]}

    return {"status": "NOT_VERIFIED", "reviews": [asdict(r) for r in reviews]}
