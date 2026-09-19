from __future__ import annotations

import app_router
from core.memory_engine import save_memory
from core.semantic_memory import memory
from core.operational_history import record_event, search_events
from services.intelligence.tavily import search as tavily_search
from services.self_healing import health_report
from services.github_safe import status as git_status
from tools.device import run as device_run
from android_capabilities import analyze_screen, capabilities as android_capabilities, capture_screen, inspect_ui_tree, toast_state
from tool_registry import Tool, register

MAX_QUERY_CHARS = 2000
MAX_MEMORY_CHARS = 12000

def _bounded_text(value: str, limit: int) -> str:
    return (value or "").strip()[:limit]

def _app_open(app: str, user_id: int | str | None = None) -> dict:
    ok, msg = app_router.open_app(app); return {"ok": ok, "message": msg, "verified": ok}

def _app_search(app: str, query: str, user_id: int | str | None = None) -> dict:
    ok, msg = app_router.search_app(app, _bounded_text(query, MAX_QUERY_CHARS)); return {"ok": ok, "message": msg, "verified": ok}

def _media_play(app: str, query: str, user_id: int | str | None = None) -> dict:
    ok, msg = app_router.play_media(app, _bounded_text(query, MAX_QUERY_CHARS))
    return {"ok": ok, "message": msg, "verified": ok, "playback_verified": False}

def _window_control(primary_app: str, secondary_app: str | None = None, mode: str = "split") -> dict:
    ok, msg = app_router.window_control(primary_app, secondary_app, mode); return {"ok": ok, "message": msg, "verified": ok}

def _memory_search(query: str, limit: int = 5, user_id: int | str | None = None) -> dict:
    return {"ok": True, "results": memory.search(_bounded_text(query, MAX_QUERY_CHARS), limit, user_id=user_id), "verified": True}

def _memory_add(content: str, category: str = "general", importance: int = 5, user_id: int | str | None = None) -> dict:
    content = _bounded_text(content, MAX_MEMORY_CHARS)
    if not content: return {"ok": False, "error": "empty_memory", "verified": False}
    if not save_memory(category, content, importance, "assistant", user_id=user_id): return {"ok": False, "error": "memory_rejected", "verified": False}
    if not memory.add(content, category, importance, "assistant", user_id=user_id): return {"ok": False, "error": "semantic_memory_rejected", "verified": False}
    return {"ok": True, "verified": True}

def _web_search(query: str, max_results: int = 5, user_id: int | str | None = None) -> dict:
    result=tavily_search(_bounded_text(query,MAX_QUERY_CHARS),max_results); result.setdefault("verified",bool(result.get("ok"))); return result

def _health(user_id: int | str | None = None) -> dict: return health_report()
def _git_status(repo: str = ".", user_id: int | str | None = None) -> dict: return git_status(repo)

def _device(action: str, user_id: int | str | None = None) -> dict:
    result=device_run(action); result.setdefault("verified",bool(result.get("ok"))); return result

def _screen_capture(user_id: int | str | None = None) -> dict:
    return capture_screen()

def _screen_analyze(user_id: int | str | None = None) -> dict:
    return analyze_screen()

def _android_capabilities(user_id: int | str | None = None) -> dict:
    return {"ok": True, "verified": True, "capabilities": android_capabilities()}

def _voice_indicator(state: str, user_id: int | str | None = None) -> dict:
    return toast_state(state)

def _history_search(query: str = "", limit: int = 10, user_id: int | str | None = None) -> dict:
    return {"ok": True, "verified": True, "results": search_events(_bounded_text(query,500),limit)}

def _history_add(event_type: str, details: str, user_id: int | str | None = None) -> dict:
    ok=record_event(_bounded_text(event_type,100),{"details":_bounded_text(details,4000),"user_id":str(user_id) if user_id is not None else None})
    return {"ok":ok,"verified":ok}

def register_all() -> None:
    register(Tool("app_open","Open an allowed app/site on the supported device.",{"type":"object","properties":{"app":{"type":"string","enum":["youtube","instagram","telegram","chrome","google","whatsapp","settings","calculator"]}},"required":["app"],"additionalProperties":False},_app_open))
    register(Tool("app_search","Search an allowed app/site.",{"type":"object","properties":{"app":{"type":"string","enum":["youtube","google","chrome"]},"query":{"type":"string","minLength":1,"maxLength":2000}},"required":["app","query"],"additionalProperties":False},_app_search))
    register(Tool("media_play","Attempt to open a media search/play request in an allowed media app.",{"type":"object","properties":{"app":{"type":"string","enum":["youtube"]},"query":{"type":"string","minLength":1,"maxLength":2000}},"required":["app","query"],"additionalProperties":False},_media_play,risk="low"))
    register(Tool("window_control","Arrange supported Android apps using a configured window/split-screen adapter.",{"type":"object","properties":{"primary_app":{"type":"string","enum":["youtube","instagram","telegram","chrome","google","whatsapp"]},"secondary_app":{"type":["string","null"],"enum":["youtube","instagram","telegram","chrome","google","whatsapp",None]},"mode":{"type":"string","enum":["split","pip","side_by_side"]}},"required":["primary_app","mode"],"additionalProperties":False},_window_control))
    register(Tool("memory_search","Search the requesting user's long-term semantic memory.",{"type":"object","properties":{"query":{"type":"string","minLength":1,"maxLength":2000},"limit":{"type":"integer","minimum":1,"maximum":10}},"required":["query"],"additionalProperties":False},_memory_search))
    register(Tool("memory_add","Store useful non-sensitive information in the requesting user's long-term memory.",{"type":"object","properties":{"content":{"type":"string","minLength":1,"maxLength":12000},"category":{"type":"string","maxLength":100},"importance":{"type":"integer","minimum":1,"maximum":10}},"required":["content"],"additionalProperties":False},_memory_add))
    register(Tool("web_search","Search the web through Tavily when local context is insufficient.",{"type":"object","properties":{"query":{"type":"string","minLength":1,"maxLength":2000},"max_results":{"type":"integer","minimum":1,"maximum":10}},"required":["query"],"additionalProperties":False},_web_search,owner_only=False,risk="medium"))
    register(Tool("system_health","Inspect recent NEXO runtime errors.",{"type":"object","properties":{},"additionalProperties":False},_health))
    register(Tool("git_status","Inspect git status of the NEXO repository or its subdirectories.",{"type":"object","properties":{"repo":{"type":"string","maxLength":500}},"additionalProperties":False},_git_status))
    register(Tool("device_action","Perform one approved Android device action.",{"type":"object","properties":{"action":{"type":"string","enum":["wifi_on","wifi_off","torch_on","torch_off","battery"]}},"required":["action"],"additionalProperties":False},_device,risk="high"))
    register(Tool("android_capabilities","Report actual available Termux:API capabilities.",{"type":"object","properties":{},"additionalProperties":False},_android_capabilities,owner_only=False,risk="low"))
    register(Tool("screen_capture","Capture the current Android screen through Termux:API; never fakes availability.",{"type":"object","properties":{},"additionalProperties":False},_screen_capture,owner_only=True,risk="medium"))
    register(Tool("screen_analyze","Capture and OCR/analyze the current Android screen; reports unavailable analysis explicitly.",{"type":"object","properties":{},"additionalProperties":False},_screen_analyze,owner_only=True,risk="medium"))
    register(Tool("ui_tree_inspect","Inspect the current Android accessibility/UI tree when the device exposes uiautomator.",{"type":"object","properties":{},"additionalProperties":False},_ui_tree,owner_only=True,risk="medium"))
    register(Tool("voice_indicator","Show the minimal ALEX voice state indicator when Termux toast is available.",{"type":"object","properties":{"state":{"type":"string","enum":["IDLE","WAKE_DETECTED","LISTENING","UNDERSTANDING","ANALYSING","DECIDING","PLANNING","AWAITING_CONFIRMATION","EXECUTING","VERIFYING","SPEAKING","ERROR"]}},"required":["state"],"additionalProperties":False},_voice_indicator,owner_only=True,risk="low"))
    register(Tool("operational_history_search","Query verified ALEX/NEXO operational history from the existing SQLite memory database.",{"type":"object","properties":{"query":{"type":"string","maxLength":500},"limit":{"type":"integer","minimum":1,"maximum":20}},"additionalProperties":False},_history_search,owner_only=True,risk="low"))
    register(Tool("operational_history_add","Record a non-sensitive operational event in the existing SQLite memory database.",{"type":"object","properties":{"event_type":{"type":"string","minLength":1,"maxLength":100},"details":{"type":"string","minLength":1,"maxLength":4000}},"required":["event_type","details"],"additionalProperties":False},_history_add,owner_only=True,risk="low"))

register_all()
