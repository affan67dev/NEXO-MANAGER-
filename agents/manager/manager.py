from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import json
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
    context: dict[str, Any] = field(default_factory=dict)

class NexoManager:
    def __init__(self) -> None:
        self.scope = json.loads(SCOPE_FILE.read_text())
        self.registry = json.loads(REGISTRY_FILE.read_text())

    def in_scope(self, text: str) -> bool:
        t = text.lower()
        keywords = {
            "app","application","backend","api","server","database","user",
            "support","email","whatsapp","security","report","moderation",
            "bug","error","crash","log","deployment","testing","monitoring",
            "authentication","login","performance","code"
        }
        return any(k in t for k in keywords)

    def classify(self, text: str) -> str:
        t = text.lower()
        if any(x in t for x in ("security","hack","vulnerability","breach","token","credential")):
            return "security"
        if any(x in t for x in ("bug","error","exception","code","backend","api","fix")):
            return "coding"
        if any(x in t for x in ("database","db","query","migration","backup")):
            return "database"
        if any(x in t for x in ("user","support","complaint","email","whatsapp","report")):
            return "support"
        if any(x in t for x in ("monitor","health","server","uptime","crash","log")):
            return "monitoring"
        if any(x in t for x in ("test","verify","verification","review","check")):
            return "verification"
        return "planning"

    def create_task(self, request: str) -> Task:
        if not self.in_scope(request):
            return Task(request=request, intent="out_of_scope", agent="manager")
        intent = self.classify(request)
        return Task(request=request, intent=intent, agent=intent)

    def status(self) -> dict[str, Any]:
        return {
            "identity": "NEXO",
            "manager_model": "Llama",
            "phase": self.scope["phase"],
            "mode": self.scope["mode"],
            "active_scope": self.scope["active_scope"],
            "deferred_scope": self.scope["deferred_scope"]
        }

if __name__ == "__main__":
    print(json.dumps(NexoManager().status(), indent=2))
