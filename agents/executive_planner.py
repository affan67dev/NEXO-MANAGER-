from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from services.llm_router import LLMRouter

LLAMA_TIMEOUT_SECONDS = 75
DEFAULT_MAX_TOKENS = 384
MAX_TOOL_CALLS_PER_RUN = 6
MAX_TOOL_RESULT_CHARS = 4000


def ask(url: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
    payload: dict[str, Any] = {"messages": messages, "temperature": 0.15, "max_tokens": max(1, min(int(max_tokens), DEFAULT_MAX_TOKENS)), "stream": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=LLAMA_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
        if not isinstance(data, dict):
            raise RuntimeError("invalid_llama_response")
        return data
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"llama_http_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"llama_unavailable:{type(exc).__name__}") from exc


def _message(data: dict[str, Any]) -> dict[str, Any]:
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    return msg if isinstance(msg, dict) else {}


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


class ExecutivePlanner:
    def __init__(self, llama_url: str):
        self.llama_url = llama_url
        self.router = LLMRouter(llama_url)

    def plan_tasks(self, goal: str, *, context: list[dict[str, Any]] | None = None, max_tasks: int = 20) -> list[dict[str, Any]]:
        """Turn one user request into bounded, data-only executable work.

        LLaMA performs request understanding and decomposition. No returned text is
        executed directly; the orchestrator validates dependencies and the tool
        registry remains the only execution boundary.
        """
        schema = {"tasks": [{
            "task_id": "task-1", "objective": "...", "intent": "...", "priority": "normal",
            "dependencies": [], "required_tools": [], "expected_result": "...",
            "kind": "sequential|parallel|dependent|complex", "resources": [],
            "timeout_seconds": 90, "max_retries": 2, "parameters": {}
        }]}
        messages = [{"role": "system", "content": (
            "You are NEXO's request analyst and planner. First understand the user's objective; "
            "do not choose a tool merely because a keyword appears. Decompose the request into the "
            "smallest meaningful executable tasks, assign a semantic intent to each task, preserve "
            "dependencies, and mark shared resources (for example app:youtube, device:audio, "
            "device:window) so conflicting work is never run concurrently. Independent tasks may be "
            "parallel. Never invent unsupported capabilities. Return ONLY valid JSON matching this shape: "
            f"{json.dumps(schema, ensure_ascii=False)}. Maximum {max_tasks} tasks."
        )}, {"role": "user", "content": goal}]
        if context:
            messages.append({"role": "system", "content": "Relevant NEXO state:\n" + json.dumps(context[-8:], ensure_ascii=False)[:6000]})
        result = self.router.call(goal, messages, None, ask)
        parsed = _extract_json(str(_message(result).get("content") or ""))
        if isinstance(parsed, dict):
            parsed = parsed.get("tasks")
        if not isinstance(parsed, list):
            return []
        return [x for x in parsed[:max(1, min(int(max_tasks), 20))] if isinstance(x, dict) and str(x.get("objective") or "").strip()]

    def run(self, goal: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], executor, owner: bool, user_id: int | str | None = None, max_steps: int = 6) -> str:
        working = list(messages)
        tool_calls_used = 0
        for _ in range(max(1, min(int(max_steps), 6))):
            result = self.router.call(goal, working, tools, ask)
            msg = _message(result)
            calls = msg.get("tool_calls") or []
            if not calls:
                return str(msg.get("content") or "I couldn't produce a result.").strip()
            working.append(msg)
            for call in calls:
                tool_calls_used += 1
                if tool_calls_used > MAX_TOOL_CALLS_PER_RUN:
                    return "The task reached the tool execution safety limit."
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args)
                    if not isinstance(args, dict):
                        raise ValueError
                    outcome = executor(name, args, owner=owner, user_id=user_id)
                except (TypeError, ValueError, json.JSONDecodeError):
                    outcome = {"ok": False, "verified": False, "error": "invalid_tool_arguments"}
                except Exception as exc:
                    outcome = {"ok": False, "verified": False, "error": f"tool_execution_failed:{type(exc).__name__}"}
                serialized = json.dumps(outcome, ensure_ascii=False)[:MAX_TOOL_RESULT_CHARS]
                working.append({"role": "tool", "tool_call_id": str(call.get("id") or name), "name": name, "content": serialized})
        return "The task reached the execution safety limit before completion."
