from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

LLAMA_TIMEOUT_SECONDS = 75
DEFAULT_MAX_TOKENS = 384
MAX_TOOL_CALLS_PER_RUN = 6


def ask(url: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
    payload: dict[str, Any] = {"messages": messages, "temperature": 0.15, "max_tokens": max_tokens, "stream": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=LLAMA_TIMEOUT_SECONDS) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        # A tool-schema error must not be hidden by silently retrying without tools.
        # Returning the real failure to the caller is safer than producing a plausible fake result.
        if tools and exc.code in {400, 404, 422}:
            raise RuntimeError(f"llama_tool_request_failed_http_{exc.code}") from exc
        raise


class ExecutivePlanner:
    def __init__(self, llama_url: str):
        self.llama_url = llama_url

    def run(self, goal: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], executor, owner: bool, max_steps: int = 6) -> str:
        working = list(messages)
        working.append({"role": "user", "content": goal})
        tool_calls_used = 0

        for _ in range(max(1, min(int(max_steps), 6))):
            result = ask(self.llama_url, working, tools)
            msg = (result.get("choices") or [{}])[0].get("message") or {}
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
                except (TypeError, json.JSONDecodeError):
                    outcome = {"ok": False, "error": "invalid_tool_arguments"}
                else:
                    if not isinstance(args, dict):
                        outcome = {"ok": False, "error": "tool_arguments_must_be_object"}
                    else:
                        try:
                            outcome = executor(name, args, owner=owner)
                        except Exception as exc:
                            # A broken tool must never crash the whole Telegram worker.
                            outcome = {"ok": False, "error": "tool_execution_failed", "message": str(exc)[:200]}

                working.append({
                    "role": "tool",
                    "tool_call_id": str(call.get("id") or name),
                    "name": name,
                    "content": json.dumps(outcome, ensure_ascii=False),
                })

        return "The task reached the execution safety limit before completion."
