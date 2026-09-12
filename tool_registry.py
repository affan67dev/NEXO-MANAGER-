from __future__ import annotations

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
    if not tool.name or not callable(tool.handler):
        raise ValueError("invalid_tool_registration")
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


def _validate_arguments(tool: Tool, arguments: dict[str, Any]) -> str | None:
    if not isinstance(arguments, dict):
        return "tool_arguments_must_be_object"
    schema = tool.parameters or {}
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    if not isinstance(properties, dict) or not isinstance(required, list):
        return "invalid_tool_schema"
    missing = [name for name in required if name not in arguments]
    if missing:
        return "missing_required_argument"
    if schema.get("additionalProperties") is False:
        unexpected = set(arguments) - set(properties)
        if unexpected:
            return "unexpected_tool_argument"

    for name, value in arguments.items():
        spec = properties.get(name)
        if not isinstance(spec, dict):
            return "invalid_tool_schema"
        expected = spec.get("type")
        if expected == "string" and not isinstance(value, str):
            return "invalid_argument_type"
        if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            return "invalid_argument_type"
        if expected == "object" and not isinstance(value, dict):
            return "invalid_argument_type"
        if expected == "array" and not isinstance(value, list):
            return "invalid_argument_type"
        if isinstance(value, str):
            if "minLength" in spec and len(value) < int(spec["minLength"]):
                return "argument_too_short"
            if "maxLength" in spec and len(value) > int(spec["maxLength"]):
                return "argument_too_long"
        if isinstance(value, int) and not isinstance(value, bool):
            if "minimum" in spec and value < int(spec["minimum"]):
                return "argument_below_minimum"
            if "maximum" in spec and value > int(spec["maximum"]):
                return "argument_above_maximum"
        enum = spec.get("enum")
        if isinstance(enum, list) and value not in enum:
            return "argument_not_allowed"
    return None


def execute(name: str, arguments: dict[str, Any], *, owner: bool) -> dict[str, Any]:
    tool = get(name)
    if not tool:
        return {"ok": False, "error": "unknown_tool"}
    if tool.owner_only and not owner:
        return {"ok": False, "error": "owner_required"}
    validation_error = _validate_arguments(tool, arguments)
    if validation_error:
        return {"ok": False, "error": validation_error}
    try:
        result = tool.handler(**arguments)
        return result if isinstance(result, dict) else {"ok": True, "result": result}
    except Exception:
        return {"ok": False, "error": "tool_execution_failed"}
