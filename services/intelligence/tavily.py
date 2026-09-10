from __future__ import annotations

import os
import json
import urllib.request


def search(query: str, max_results: int = 5) -> dict:
    query = (query or "").strip()
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not query:
        return {"ok": False, "error": "empty_query"}
    if not key:
        return {"ok": False, "configured": False, "error": "TAVILY_API_KEY is not configured"}
    payload = {"api_key": key, "query": query, "search_depth": "basic", "max_results": max(1, min(int(max_results), 10)), "include_answer": True}
    req = urllib.request.Request("https://api.tavily.com/search", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read())
        return {"ok": True, "answer": data.get("answer"), "results": [{"title": x.get("title"), "url": x.get("url"), "content": (x.get("content") or "")[:1500]} for x in data.get("results", [])]}
    except Exception as exc:
        return {"ok": False, "configured": True, "error": type(exc).__name__}
