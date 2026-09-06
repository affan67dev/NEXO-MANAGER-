def testing_task(request: str) -> dict:
    return {
        "agent": "testing",
        "task": request,
        "workflow": ["identify_tests", "run_tests", "collect_results", "report_failures"]
    }
