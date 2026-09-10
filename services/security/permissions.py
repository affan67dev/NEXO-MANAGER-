from __future__ import annotations

import re
from pathlib import Path

INJECTION = re.compile(r"(?is)(ignore|disregard).{0,80}(previous|system|developer)|reveal.{0,40}(prompt|instruction)|jailbreak")
OWNER_ONLY = {"device_action", "filesystem_write", "github_write", "git_push", "scheduler_write", "system_health", "git_status"}


def inspect_request(text: str, user_id: int | str | None, owner_id: int | None) -> dict:
    value = text if isinstance(text, str) else ""
    hit = bool(INJECTION.search(value))
    return {"safe": not hit, "prompt_injection": hit, "owner": owner_id is not None and str(user_id) == str(owner_id)}


def authorize(tool: str, owner: bool) -> dict:
    return {"allowed": bool(owner) if tool in OWNER_ONLY else True, "reason": "owner_required" if tool in OWNER_ONLY and not owner else "policy_allows"}


def safe_path(path: str, base: str | Path) -> bool:
    try:
        root = Path(base).expanduser().resolve()
        target = Path(path).expanduser().resolve()
        if root not in target.parents:
            return False
        rel = target.relative_to(root).as_posix().lower()
        blocked = {".env", ".nexo.env", "data/memory.db"}
        return rel not in blocked and not any(rel.endswith(x) for x in (".pem", ".key", ".p12", ".sqlite", ".sqlite3"))
    except Exception:
        return False
