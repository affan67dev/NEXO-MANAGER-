from __future__ import annotations

import app_router
from core.memory_engine import save_memory
from core.semantic_memory import memory
from services.intelligence.tavily import search as tavily_search
from services.self_healing import health_report
from services.github_safe import status as git_status
from tools.device import run as device_run
from tool_registry import Tool, register

MAX_QUERY_CHARS = 2000
MAX_MEMORY_CHARS = 12000


def _bounded_text(value: str, limit: int) -> str:
    return (value or "").strip()[:limit]


def _app_open(app: str) -> dict:
    ok, msg = app_router.open_app(app)
    return {"ok": ok, "message": msg, "verified": ok}


def _app_search(app: str, query: str) -> dict:
    ok, msg = app_router.search_app(app, _bounded_text(query, MAX_QUERY_CHARS))
    return {"ok": ok, "message": msg, "verified": ok}


def _memory_search(query: str, limit: int = 5) -> dict:
    return {"ok": True, "results": memory.search(_bounded_text(query, MAX_QUERY_CHARS), limit)}


def _memory_add(content: str, category: str = "general", importance: int = 5) -> dict:
    content = _bounded_text(content, MAX_MEMORY_CHARS)
    if not content:
        return {"ok": False, "error": "empty_memory"}
    if not save_memory(category, content, importance, "assistant"):
        return {"ok": False, "error": "memory_rejected"}
    if not memory.add(content, category, importance, "assistant"):
        return {"ok": False, "error": "semantic_memory_rejected"}
    return {"ok": True, "verified": True}


def _web_search(query: str, max_results: int = 5) -> dict:
    return tavily_search(_bounded_text(query, MAX_QUERY_CHARS), max_results)


def _health() -> dict:
    return health_report()


def _git_status(repo: str = ".") -> dict:
    return git_status(repo)


def _device(action: str) -> dict:
    return device_run(action)


def register_all() -> None:
    register(Tool("app_open", "Open an allowed Android app/site.", {"type":"object","properties":{"app":{"type":"string","enum":["youtube","instagram","telegram","chrome","google"]}},"required":["app"],"additionalProperties":False}, _app_open))
    register(Tool("app_search", "Search an allowed app/site.", {"type":"object","properties":{"app":{"type":"string","enum":["youtube","google","chrome"]},"query":{"type":"string","minLength":1,"maxLength":2000}},"required":["app","query"],"additionalProperties":False}, _app_search))
    register(Tool("memory_search", "Search long-term semantic memory.", {"type":"object","properties":{"query":{"type":"string","minLength":1,"maxLength":2000},"limit":{"type":"integer","minimum":1,"maximum":10}},"required":["query"],"additionalProperties":False}, _memory_search))
    register(Tool("memory_add", "Store useful non-sensitive information in long-term memory.", {"type":"object","properties":{"content":{"type":"string","minLength":1,"maxLength":12000},"category":{"type":"string","maxLength":100},"importance":{"type":"integer","minimum":1,"maximum":10}},"required":["content"],"additionalProperties":False}, _memory_add))
    register(Tool("web_search", "Search the web through Tavily when local context is insufficient.", {"type":"object","properties":{"query":{"type":"string","minLength":1,"maxLength":2000},"max_results":{"type":"integer","minimum":1,"maximum":10}},"required":["query"],"additionalProperties":False}, _web_search, owner_only=False, risk="medium"))
    register(Tool("system_health", "Inspect recent NEXO runtime errors.", {"type":"object","properties":{},"additionalProperties":False}, _health))
    register(Tool("git_status", "Inspect git status of the NEXO repository or its subdirectories.", {"type":"object","properties":{"repo":{"type":"string","maxLength":500}},"additionalProperties":False}, _git_status))
    register(Tool("device_action", "Perform one approved Android device action.", {"type":"object","properties":{"action":{"type":"string","enum":["wifi_on","wifi_off","torch_on","torch_off","battery"]}},"required":["action"],"additionalProperties":False}, _device, risk="high"))


register_all()
