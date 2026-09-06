def coding_task(request: str) -> dict:
    return {
        "agent": "coding",
        "task": request,
        "workflow": ["inspect", "plan", "change", "test", "security_review", "verify"]
    }
