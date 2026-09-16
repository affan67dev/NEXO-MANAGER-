from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "memory.db"
MIGRATION = BASE / "migrations" / "001_portfolio_ai.sql"

SECRET = re.compile(r"(?i)(api[_ -]?key|password|token|secret|private[_ -]?(?:key|repo|repository|database)|authorization|bearer)\s*[:=]?\s*\S+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(db_path: Path | str = DB) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(db_path: Path | str = DB) -> None:
    with connect(db_path) as conn:
        if MIGRATION.exists():
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def save_visitor_turn(session_id: str, role: str, content: str, *, db_path: Path | str = DB) -> bool:
    if role not in {"user", "assistant"} or not session_id or not content:
        return False
    value = str(content).strip()
    if not value or len(value) > 12000 or SECRET.search(value):
        return False
    ensure_schema(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO visitor_conversation(session_id,role,content,created_at,channel) VALUES(?,?,?,?,?)",
            (session_id, role, value, _now(), "portfolio_web"),
        )
    return True


def recent_visitor_turns(session_id: str, limit: int = 8, *, db_path: Path | str = DB) -> list[tuple[str, str]]:
    if not session_id:
        return []
    ensure_schema(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT role,content FROM visitor_conversation WHERE session_id=? AND channel='portfolio_web' ORDER BY id DESC LIMIT ?",
            (session_id, max(1, min(int(limit), 8))),
        ).fetchall()
    return list(reversed(rows))


def upsert_knowledge(*, source: str, repository: str, file_path: str, project: str, content: str, visibility: str = "public", version_sha: str = "", indexed: bool = True, db_path: Path | str = DB) -> int:
    value = str(content or "").strip()
    if not value or len(value) > 100000 or SECRET.search(value):
        raise ValueError("knowledge_content_rejected")
    if visibility not in {"public", "private", "internal"}:
        raise ValueError("invalid_visibility")
    ensure_schema(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO knowledge_documents(source,repository,file_path,project,content,visibility,version_sha,created_at,updated_at,indexed_at) VALUES(?,?,?,?,?,?,?,?,?,CASE WHEN ? THEN ? ELSE NULL END) ON CONFLICT(repository,file_path,version_sha) DO UPDATE SET source=excluded.source,project=excluded.project,content=excluded.content,visibility=excluded.visibility,updated_at=excluded.updated_at,indexed_at=excluded.indexed_at",
            (source, repository, file_path, project, value, visibility, version_sha, _now(), _now(), indexed, _now()),
        )
        return int(cur.lastrowid or 0)


def retrieve_knowledge(query: str, *, channel: str, scope: str, project: str | None = None, limit: int = 5, db_path: Path | str = DB) -> list[dict[str, Any]]:
    visibility_by_scope = {
        "public_portfolio": {"public"},
        "telegram_public": {"public"},
        "owner_admin": {"public", "private", "internal"},
    }
    if channel not in {"portfolio_web", "telegram"} or scope not in visibility_by_scope:
        return []
    if channel == "portfolio_web" and scope != "public_portfolio":
        return []
    if channel == "telegram" and scope == "public_portfolio":
        return []
    terms = [t for t in re.findall(r"[\w-]+", (query or "").lower()) if len(t) > 2][:8]
    if not terms:
        return []
    ensure_schema(db_path)
    visibility = visibility_by_scope[scope]
    placeholders = ",".join("?" for _ in visibility)
    where = [f"visibility IN ({placeholders})", "indexed_at IS NOT NULL"]
    params: list[Any] = list(sorted(visibility))
    if project:
        where.append("project=?")
        params.append(project)
    relevance = " + ".join(["CASE WHEN lower(content) LIKE ? OR lower(project) LIKE ? OR lower(file_path) LIKE ? THEN 1 ELSE 0 END" for _ in terms])
    for term in terms:
        params.extend((f"%{term}%", f"%{term}%", f"%{term}%"))
    params.append(max(1, min(int(limit), 10)))
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT source,repository,file_path,project,content,visibility,version_sha,updated_at FROM knowledge_documents WHERE {' AND '.join(where)} ORDER BY ({relevance}) DESC, updated_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [
        {"source": r[0], "repository": r[1], "file_path": r[2], "project": r[3], "content": r[4], "visibility": r[5], "version_sha": r[6], "updated_at": r[7]}
        for r in rows
    ]
