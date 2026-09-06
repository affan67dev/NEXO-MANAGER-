def verify(output: dict, evidence: list | None = None) -> dict:
    evidence = evidence or []
    return {
        "verified": bool(evidence),
        "evidence_count": len(evidence),
        "output": output,
        "note": "No evidence means the result must not be claimed as verified."
    }
