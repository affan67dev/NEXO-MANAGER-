from __future__ import annotations
from agents.verification.verification import verify

def run_verification(output: dict, evidence: list | None = None) -> dict:
    result = verify(output, evidence)
    if not result["verified"]:
        result["status"] = "not_verified"
        result["recommendation"] = "Do not claim completion without evidence."
    else:
        result["status"] = "verified"
    return result
