def plan(request: str) -> dict:
    return {
        "agent": "planning",
        "objective": request,
        "steps": [
            "understand requirements",
            "inspect authorized context",
            "identify affected application component",
            "select specialist",
            "define verification criteria"
        ]
    }
