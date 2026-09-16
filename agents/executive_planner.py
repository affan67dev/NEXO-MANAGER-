from __future__ import annotations

import json
import re
from typing import Any

from services.context_budget import fit_messages, output_tokens
from services.llm_provider import LLMProvider, create_llm_provider
from services.llm_router import LLMRouter

MAX_TOOL_CALLS_PER_RUN = 6
MAX_TOOL_RESULT_CHARS = 4000


def _message(data: dict[str, Any]) -> dict[str, Any]:
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    return msg if isinstance(msg, dict) else {}


def _clean_response_text(content: Any, reasoning_content: Any = "") -> str:
    """Return only user-facing final text; never expose model reasoning traces."""
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
    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or create_llm_provider()
        self.router = LLMRouter(self.provider)

    def _route_call(self, goal: str, messages: list[dict[str, Any]], tools, *, intent: str | None):
        fitted = fit_messages(messages, tools)
        return self.router.call(goal, fitted, tools, intent=intent)

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
