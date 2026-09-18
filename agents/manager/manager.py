from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCOPE_FILE = ROOT / "config" / "app_scope.json"
REGISTRY_FILE = ROOT / "config" / "agent_registry.json"


@dataclass
class Task:
    request: str
    intent: str = "unknown"
    priority: str = "normal"
    agent: str = "manager"
    requires_approval: bool = False
    objective: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    expected_result: str = ""
    state: str = "queued"
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:10]}")
    context: dict[str, Any] = field(default_factory=dict)
    resources: list[str] = field(default_factory=list)


class NexoManager:
    """Central request gate; execution remains downstream in planner/tools. ALEX is the user-facing identity."""

    def __init__(self) -> None:
        self.scope = json.loads(SCOPE_FILE.read_text())
        self.registry = json.loads(REGISTRY_FILE.read_text())

    def in_scope(self, text: str) -> bool:
        t = (text or "").lower()
        keywords = {"app", "application", "backend", "api", "server", "database", "user", "support", "email", "whatsapp", "security", "report", "moderation", "bug", "error", "crash", "log", "deployment", "testing", "monitoring", "authentication", "login", "performance", "code", "youtube", "instagram", "telegram", "chrome", "google", "open", "launch", "khol", "kholo", "play", "song", "music", "wifi", "torch", "battery", "split", "window", "pip", "device", "phone", "tablet", "android", "computer", "mac", "windows"}
        return any(k in t for k in keywords)

    def classify(self, text: str) -> str:
        t = (text or "").strip().lower()
        if not t:
            return "conversation"
        if any(x in t for x in ("security", "hack", "vulnerability", "breach", "token", "credential")): return "security"
        if any(x in t for x in ("delete", "wipe", "factory reset", "shutdown", "format", "payment", "send message")): return "security"
        if any(x in t for x in ("youtube", "instagram", "telegram", "whatsapp", "chrome", "google", "open", "launch", "play", "song", "music", "wifi", "torch", "battery", "split", "window", "pip", "device", "phone", "tablet")): return "device_control"
        if any(x in t for x in ("bug", "error", "exception", "code", "backend", "api", "fix", "debug", "root cause")): return "coding"
        if any(x in t for x in ("database", "db", "query", "migration", "backup")): return "database"
        if any(x in t for x in ("user", "support", "complaint", "email", "report")): return "support"
        if any(x in t for x in ("monitor", "health", "server", "uptime", "crash", "log")): return "monitoring"
        if any(x in t for x in ("test", "verify", "verification", "review", "check")): return "verification"
        return "conversation"

    def complexity_signals(self, text: str) -> dict[str, Any]:
        t = (text or "").strip().lower()
        reasoning_terms = (
            "analyze", "analyse", "reason", "reasoning", "compare", "tradeoff",
            "root cause", "deep dive", "in depth", "step by step", "architecture",
            "design", "debug", "diagnose", "evaluate", "critically", "why does",
            "why is", "multiple possibilities", "pros and cons", "complex", "detailed",
        )
        matched = [term for term in reasoning_terms if term in t]
        word_count = len(t.split())
        return {
            "matched_reasoning_signals": matched,
            "word_count": word_count,
            "char_count": len(t),
            "reasoning_heavy": bool(matched) or word_count >= 120,
        }

    def create_task(self, request: str) -> Task:
        objective = (request or "").strip()
        intent = self.classify(objective)
        if intent == "conversation":
            return Task(request=request, objective=objective, intent=intent, agent="manager")
        if not self.in_scope(objective):
            return Task(request=request, objective=objective, intent="out_of_scope", agent="manager")
        return Task(request=request, objective=objective, intent=intent, agent=intent, context={"request_received_at": uuid.uuid4().hex})

    def structured_task(self, request: str, *, task_id: str | None = None, dependencies: list[str] | None = None, required_tools: list[str] | None = None, expected_result: str = "", priority: str = "normal", parameters: dict[str, Any] | None = None, resources: list[str] | None = None, intent: str | None = None) -> Task:
        task = self.create_task(request)
        task.task_id = task_id or task.task_id
        task.dependencies = list(dependencies or [])
        task.required_tools = list(required_tools or [])
        task.expected_result = expected_result or f"Successful completion of: {task.objective}"
        task.priority = priority
        task.parameters = dict(parameters or {})
        task.resources = list(resources or [])
        if intent:
            task.intent = intent
        return task

    def status(self) -> dict[str, Any]:
        return {"identity": "ALEX", "manager_model": "Qwen3-4B", "phase": self.scope["phase"], "mode": self.scope["mode"], "active_scope": self.scope["active_scope"], "deferred_scope": self.scope["deferred_scope"]}


if __name__ == "__main__":
    print(json.dumps(NexoManager().status(), indent=2))
