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
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in _REGISTRY.values()
    ]


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
    return {
        "role": "tool",
        "tool_call_id": name,
        "name": name,
        "content": json.dumps(result, ensure_ascii=False),
    }


def _web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    from tools.web_search import search_web

    return {"ok": True, "results": search_web(query, max_results=max_results)}


def _memory_search(query: str, limit: int = 5) -> dict[str, Any]:
    from core.memory_engine import search_memory

    return {"ok": True, "results": search_memory(query, limit=limit)}


def _device_action(action: str, **_: Any) -> dict[str, Any]:
    # Device execution remains behind the runtime's owner/permission layer.
    # The registry exposes the schema without granting arbitrary shell access.
    return {"ok": False, "error": "device_action_requires_runtime_executor", "action": action}


register(
    Tool(
        name="web_search",
        description="Search the web for current information when local context is insufficient.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_web_search,
        owner_only=True,
        risk="medium",
    )
)

register(
    Tool(
        name="memory_search",
        description="Search NEXO's persistent local memory for relevant stored context.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_memory_search,
        owner_only=True,
        risk="low",
    )
)

register(
    Tool(
        name="device_action",
        description="Request an approved Android device action through the guarded runtime executor.",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        handler=_device_action,
        owner_only=True,
        risk="high",
    )
)
