from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_OUTPUT = 4000


def _allowed_repo(repo: str) -> Path | None:
    try:
        raw = Path(repo or ".").expanduser()
        target = (ROOT / raw).resolve() if not raw.is_absolute() else raw.resolve()
        if target != ROOT and ROOT not in target.parents:
            return None
        return target
    except (OSError, RuntimeError):
        return None


def status(repo: str = ".") -> dict[str, object]:
    target = _allowed_repo(repo)
    if target is None:
        return {"ok": False, "verified": False, "error": "repository_path_not_allowed"}
    if not target.is_dir() or not (target / ".git").exists():
        return {"ok": False, "verified": False, "error": "git_repository_not_found"}
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "status", "--short", "--branch"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False, "verified": False, "error": "git_status_failed"}
    if result.returncode != 0:
        return {"ok": False, "verified": False, "error": "git_status_failed"}
    return {
        "ok": True,
        "verified": True,
        "repository": str(target),
        "status": result.stdout[-MAX_OUTPUT:],
    }
