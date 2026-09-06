def database_task(request: str) -> dict:
    return {
        "agent": "database",
        "task": request,
        "workflow": ["inspect_health", "check_errors", "protect_data", "recommend_action", "verify"]
    }
