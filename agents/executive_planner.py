from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

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
        with urllib.request.urlopen(req, timeout=LLAMA_TIMEOUT_SECONDS) as r:
            data = json.loads(r.read())
        if not isinstance(data, dict):
            raise RuntimeError("invalid_llama_response")
        return data
    except urllib.error.HTTPError as exc:
        if tools and exc.code in {400, 404, 422}:
            raise RuntimeError(f"llama_tool_request_failed_http_{exc.code}") from exc
        raise


class ExecutivePlanner:
    def __init__(self, llama_url: str):
        self.llama_url = llama_url

    def run(self, goal: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], executor, owner: bool, user_id: int | str | None = None, max_steps: int = 6) -> str:
        working = list(messages)
        working.append({"role": "user", "content": str(goal)[:2000]})
        tool_calls_used = 0

        for _ in range(max(1, min(int(max_steps), 6))):
            result = ask(self.llama_url, working, tools)
            msg = (result.get("choices") or [{}])[0].get("message") or {}
            if not isinstance(msg, dict):
                return "I couldn't produce a valid result."
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
                            outcome = executor(name, args, owner=owner, user_id=user_id)
                        except TypeError:
                            # Compatibility for simple test/custom executors that do not accept user_id.
                            try:
                                outcome = executor(name, args, owner=owner)
                            except Exception:
                                outcome = {"ok": False, "error": "tool_execution_failed"}
                        except Exception:
                            outcome = {"ok": False, "error": "tool_execution_failed"}

                serialized = json.dumps(outcome, ensure_ascii=False)[:MAX_TOOL_RESULT_CHARS]
                working.append({
                    "role": "tool",
                    "tool_call_id": str(call.get("id") or name),
                    "name": name,
                    "content": serialized,
                })

        return "The task reached the execution safety limit before completion."
