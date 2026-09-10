from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., dict[str, Any]]
    owner_only: bool = True
    risk: str = "low"

_REGISTRY: dict[str, Tool] = {}

def register(tool: Tool) -> None:
    _REGISTRY[tool.name] = tool

def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)

def schemas() -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in _REGISTRY.values()]

def names() -> list[str]:
    return list(_REGISTRY)

def execute(name: str, arguments: dict[str, Any], *, owner: bool) -> dict[str, Any]:
    tool = get(name)
    if not tool:
        return {"ok": False, "error": "unknown_tool"}
    if tool.owner_only and not owner:
        return {"ok": False, "error": "owner_required"}
    try:
        result = tool.handler(**arguments)
        return result if isinstance(result, dict) else {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)[:300]}

def tool_message(name: str, result: dict[str, Any]) -> dict[str, str]:
    return {"role": "tool", "tool_call_id": name, "name": name, "content": json.dumps(result, ensure_ascii=False)}
