from __future__ import annotations

import app_router
from core.memory_engine import save_memory
from core.semantic_memory import memory
from services.intelligence.tavily import search as tavily_search
from services.self_healing import health_report
from services.github_safe import status as git_status
from tools.device import run as device_run
from tool_registry import Tool, register


def _app_open(app: str) -> dict:
    ok, msg = app_router.open_app(app)
    return {"ok": ok, "message": msg, "verified": False}

def _app_search(app: str, query: str) -> dict:
    ok, msg = app_router.search_app(app, query)
    return {"ok": ok, "message": msg, "verified": False}

def _memory_search(query: str, limit: int = 5) -> dict:
    return {"ok": True, "results": memory.search(query, limit)}

def _memory_add(content: str, category: str = "general", importance: int = 5) -> dict:
    ok = save_memory(category, content, importance, "assistant") and memory.add(content, category, importance, "assistant")
    return {"ok": ok}

def _web_search(query: str, max_results: int = 5) -> dict:
    return tavily_search(query, max_results)

def _health() -> dict:
    return health_report()

def _git_status(repo: str = ".") -> dict:
    return git_status(repo)

def _device(action: str) -> dict:
    return device_run(action)

def register_all() -> None:
    register(Tool("app_open", "Open an allowed Android app/site.", {"type":"object","properties":{"app":{"type":"string","enum":["youtube","instagram","telegram","chrome","google"]}},"required":["app"]}, _app_open))
    register(Tool("app_search", "Search an allowed app/site.", {"type":"object","properties":{"app":{"type":"string","enum":["youtube","google","chrome"]},"query":{"type":"string","minLength":1}},"required":["app","query"]}, _app_search))
    register(Tool("memory_search", "Search long-term semantic memory.", {"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":10}},"required":["query"]}, _memory_search))
    register(Tool("memory_add", "Store useful non-sensitive information in long-term memory.", {"type":"object","properties":{"content":{"type":"string"},"category":{"type":"string"},"importance":{"type":"integer","minimum":1,"maximum":10}},"required":["content"]}, _memory_add))
    register(Tool("web_search", "Search the web through Tavily when local context is insufficient.", {"type":"object","properties":{"query":{"type":"string"},"max_results":{"type":"integer","minimum":1,"maximum":10}},"required":["query"]}, _web_search, owner_only=False))
    register(Tool("system_health", "Inspect recent NEXO runtime errors.", {"type":"object","properties":{}}, _health))
    register(Tool("git_status", "Inspect git status of a local repository.", {"type":"object","properties":{"repo":{"type":"string"}}}, _git_status))
    register(Tool("device_action", "Perform one approved Android device action.", {"type":"object","properties":{"action":{"type":"string","enum":["wifi_on","wifi_off","torch_on","torch_off","battery"]}},"required":["action"]}, _device))

register_all()
