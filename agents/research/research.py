def research_task(request: str) -> dict:
    return {
        "agent": "research",
        "task": request,
        "rules": ["use_authorized_sources", "do_not_invent_facts", "record_uncertainty"]
    }
