from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from services.llm_router import LLMRouter
from services.context_budget import fit_messages, output_tokens

QWEN_TIMEOUT_SECONDS = 120
DEFAULT_MAX_TOKENS = 256
MAX_TOOL_CALLS_PER_RUN = 6
MAX_TOOL_RESULT_CHARS = 4000


def _timeout_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("NEXO_LLM_READ_TIMEOUT_SECONDS", str(QWEN_TIMEOUT_SECONDS))))
    except (TypeError, ValueError):
        return QWEN_TIMEOUT_SECONDS


def _thinking_disabled() -> bool:
    return os.getenv("NEXO_QWEN_DISABLE_THINKING", "true").strip().lower() in {"1", "true", "yes", "on"}


def ask(url: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": messages,
        "temperature": 0.15,
        "max_tokens": max(1, min(int(max_tokens), output_tokens())),
        "stream": False,
    }
    if _thinking_disabled():
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=_timeout_seconds()) as response:
            data = json.loads(response.read())
        if not isinstance(data, dict):
            raise RuntimeError("invalid_model_response")
        return data
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"model_http_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"model_unavailable:{type(exc).__name__}") from exc


def _message(data: dict[str, Any]) -> dict[str, Any]:
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    return msg if isinstance(msg, dict) else {}


def _clean_response_text(content: Any, reasoning_content: Any = "") -> str:
    """Return only user-facing final text; never expose Qwen reasoning traces."""
    text = str(content or "").strip()
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<think>.*$", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</think>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}|\[.*\]", text, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _tool_key(call: dict[str, Any]) -> str:
    fn = call.get("function") or {}
    raw_args = fn.get("arguments") or "{}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except (TypeError, ValueError, json.JSONDecodeError):
        args = raw_args
    return json.dumps({"name": str(fn.get("name") or ""), "arguments": args}, sort_keys=True, ensure_ascii=False, default=str)


class ExecutivePlanner:
    def __init__(self, qwen_url: str):
        self.qwen_url = qwen_url
        self.router = LLMRouter(qwen_url)

    def _route_call(self, goal: str, messages: list[dict[str, Any]], tools, *, intent: str | None):
        fitted = fit_messages(self.qwen_url, messages, tools)
        return self.router.call(goal, fitted, tools, ask, intent=intent)

    def plan_tasks(self, goal: str, *, context: list[dict[str, Any]] | None = None, max_tasks: int = 20, intent: str | None = None) -> list[dict[str, Any]]:
        schema = {"tasks": [{"task_id": "task-1", "objective": "...", "intent": "...", "priority": "normal", "dependencies": [], "required_tools": [], "expected_result": "...", "kind": "sequential|parallel|dependent|complex", "resources": [], "timeout_seconds": 90, "max_retries": 2, "parameters": {}}]}
        messages = [{"role": "system", "content": ("You are NEXO's request analyst and planner. First understand the user's objective; do not choose a tool merely because a keyword appears. Decompose the request into the smallest meaningful executable tasks, assign a semantic intent to each task, preserve dependencies, and mark shared resources so conflicting work is never run concurrently. Never invent unsupported capabilities. Return ONLY valid JSON matching this shape: " + json.dumps(schema, ensure_ascii=False) + f". Maximum {max_tasks} tasks.")}, {"role": "user", "content": goal}]
        if context:
            messages.append({"role": "system", "content": "Relevant NEXO state:\n" + json.dumps(context[-8:], ensure_ascii=False)[:3000]})
        result = self._route_call(goal, messages, None, intent=intent)
        parsed = _extract_json(_clean_response_text(_message(result).get("content"), _message(result).get("reasoning_content")))
        if isinstance(parsed, dict):
            parsed = parsed.get("tasks")
        if not isinstance(parsed, list):
            return []
        return [x for x in parsed[:max(1, min(int(max_tasks), 20))] if isinstance(x, dict) and str(x.get("objective") or "").strip()]

    def run(self, goal: str, messages: list[dict[str, Any]], tools, executor, owner: bool, user_id: int | str | None = None, max_steps: int = 6, intent: str | None = None) -> str:
        working = list(messages)
        tool_calls_used = 0
        executed_tool_keys: set[str] = set()
        for _ in range(max(1, min(int(max_steps), 6))):
            result = self._route_call(goal, working, tools, intent=intent)
            msg = _message(result)
            calls = msg.get("tool_calls") or []
            if not calls:
                answer = _clean_response_text(msg.get("content"), msg.get("reasoning_content"))
                if not answer:
                    raise RuntimeError("empty_model_response")
                return answer
            working.append(msg)
            for call in calls:
                key = _tool_key(call)
                if key in executed_tool_keys:
                    working.append({"role": "tool", "tool_call_id": str(call.get("id") or "duplicate"), "name": str((call.get("function") or {}).get("name") or ""), "content": json.dumps({"ok": False, "verified": False, "error": "duplicate_tool_call_blocked"})})
                    continue
                tool_calls_used += 1
                if tool_calls_used > MAX_TOOL_CALLS_PER_RUN:
                    raise RuntimeError("tool_execution_safety_limit")
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args)
                    if not isinstance(args, dict):
                        raise ValueError
                    outcome = executor(name, args, owner=owner, user_id=user_id)
                    executed_tool_keys.add(key)
                except (TypeError, ValueError, json.JSONDecodeError):
                    outcome = {"ok": False, "verified": False, "error": "invalid_tool_arguments"}
                except Exception:
                    outcome = {"ok": False, "verified": False, "error": "tool_execution_failed"}
                serialized = json.dumps(outcome, ensure_ascii=False)[:MAX_TOOL_RESULT_CHARS]
                working.append({"role": "tool", "tool_call_id": str(call.get("id") or name), "name": name, "content": serialized})
        raise RuntimeError("planner_execution_safety_limit")
