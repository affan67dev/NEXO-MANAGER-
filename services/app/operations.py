from __future__ import annotations
from agents.manager.manager import NexoManager

class AppOperations:
    def __init__(self):
        self.manager = NexoManager()

    def handle(self, request: str) -> dict:
        task = self.manager.create_task(request)
        return {
            "task": task.request,
            "intent": task.intent,
            "agent": task.agent,
            "scope": "APP_ONLY",
            "requires_approval": task.requires_approval
        }
