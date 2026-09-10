from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def ask(url: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, max_tokens: int = 512) -> dict[str, Any]:
    payload: dict[str, Any] = {"messages": messages, "temperature": 0.15, "max_tokens": max_tokens, "stream": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        if tools and exc.code in {400, 404, 422}:
            fallback = {"messages": messages, "temperature": 0.15, "max_tokens": max_tokens, "stream": False}
            req = urllib.request.Request(url, data=json.dumps(fallback).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        raise

class ExecutivePlanner:
    def __init__(self, llama_url: str):
        self.llama_url = llama_url

    def run(self, goal: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], executor, owner: bool, max_steps: int = 6) -> str:
        working = list(messages)
        working.append({"role": "user", "content": goal})
        for _ in range(max_steps):
            result = ask(self.llama_url, working, tools)
            msg = (result.get("choices") or [{}])[0].get("message") or {}
            calls = msg.get("tool_calls") or []
            if not calls:
                return str(msg.get("content") or "I couldn't produce a result.").strip()
            working.append(msg)
            for call in calls:
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                outcome = executor(name, args, owner=owner)
                working.append({"role": "tool", "tool_call_id": str(call.get("id") or name), "name": name, "content": json.dumps(outcome, ensure_ascii=False)})
        return "The task reached the execution safety limit before completion."
