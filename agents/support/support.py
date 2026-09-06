def support_task(request: str) -> dict:
    return {
        "agent": "support",
        "task": request,
        "workflow": ["classify", "check_known_issue", "check_policy", "draft_response", "verify", "escalate_if_needed"]
    }
