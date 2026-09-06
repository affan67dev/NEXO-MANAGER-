def security_task(request: str) -> dict:
    return {
        "agent": "security",
        "task": request,
        "workflow": ["detect", "analyze", "contain_when_authorized", "recommend", "verify", "document"]
    }
