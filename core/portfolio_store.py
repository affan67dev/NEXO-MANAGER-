from __future__ import annotations

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
METADATA_COLUMNS = {
    "source_type": "TEXT NOT NULL DEFAULT 'legacy'",
    "scope": "TEXT NOT NULL DEFAULT 'public_portfolio'",
    "title": "TEXT NOT NULL DEFAULT ''",
    "source_url": "TEXT NOT NULL DEFAULT ''",
    "content_hash": "TEXT NOT NULL DEFAULT ''",
    "last_ingested_at": "TEXT",
}

SECRET = re.compile(
    r"(?i)(api[_ -]?key|password|token|secret|private[_ -]?(?:key|repo|repository|database)|authorization|bearer)\s*[:=]?\s*\S+"
)


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
        existing = {row[1] for row in conn.execute("PRAGMA table_info(knowledge_documents)")}
        for name, definition in METADATA_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE knowledge_documents ADD COLUMN {name} {definition}")


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


def upsert_knowledge(
    *,
    source: str,
    repository: str,
    file_path: str,
    project: str,
    content: str,
    visibility: str = "public",
    version_sha: str = "",
    indexed: bool = True,
    source_type: str = "legacy",
    scope: str = "public_portfolio",
    title: str = "",
    source_url: str = "",
    content_hash: str = "",
    last_ingested_at: str | None = None,
    db_path: Path | str = DB,
) -> int:
    value = str(content or "").strip()
    if not value or len(value) > 100000 or SECRET.search(value):
        raise ValueError("knowledge_content_rejected")
    if visibility not in {"public", "private", "internal"}:
        raise ValueError("invalid_visibility")
    if scope not in {"public_portfolio", "telegram_public", "owner_admin"}:
        raise ValueError("invalid_scope")
    ensure_schema(db_path)
    now = _now()
    ingested = last_ingested_at or now
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_documents(
                source,source_type,repository,file_path,project,title,source_url,
                content,visibility,scope,version_sha,content_hash,
                created_at,updated_at,last_ingested_at,indexed_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CASE WHEN ? THEN ? ELSE NULL END)
            ON CONFLICT(repository,file_path,version_sha) DO UPDATE SET
                source=excluded.source,
                source_type=excluded.source_type,
                project=excluded.project,
                title=excluded.title,
                source_url=excluded.source_url,
                content=excluded.content,
                visibility=excluded.visibility,
                scope=excluded.scope,
                content_hash=excluded.content_hash,
                updated_at=excluded.updated_at,
                last_ingested_at=excluded.last_ingested_at,
                indexed_at=excluded.indexed_at
            """,
            (
                source,
                source_type,
                repository,
                file_path,
                project,
                title,
                source_url,
                value,
                visibility,
                scope,
                version_sha,
                content_hash,
                now,
                now,
                ingested,
                indexed,
                now,
            ),
        )
        return int(cur.lastrowid or 0)


def knowledge_version_exists(repository: str, version_sha: str, *, db_path: Path | str = DB) -> bool:
    if not repository or not version_sha:
        return False
    ensure_schema(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM knowledge_documents WHERE repository=? AND version_sha=? AND visibility='public' AND scope='public_portfolio' LIMIT 1",
            (repository, version_sha),
        ).fetchone()
    return row is not None


def prune_public_repository_versions(repository: str, keep_version_sha: str, *, db_path: Path | str = DB) -> int:
    if not repository or not keep_version_sha:
        return 0
    ensure_schema(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM knowledge_documents WHERE repository=? AND visibility='public' AND scope='public_portfolio' AND version_sha<>?",
            (repository, keep_version_sha),
        )
        return int(cur.rowcount or 0)


def retrieve_knowledge(
    query: str,
    *,
    channel: str,
    scope: str,
    project: str | None = None,
    limit: int = 5,
    db_path: Path | str = DB,
) -> list[dict[str, Any]]:
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
    where = [f"visibility IN ({placeholders})", "indexed_at IS NOT NULL", "scope=?"]
    params: list[Any] = list(sorted(visibility)) + [scope]
    if project:
        where.append("project=?")
        params.append(project)

    relevance = " + ".join(
        [
            "CASE WHEN lower(content) LIKE ? OR lower(project) LIKE ? OR lower(file_path) LIKE ? OR lower(title) LIKE ? THEN 1 ELSE 0 END"
            for _ in terms
        ]
    )
    for term in terms:
        params.extend((f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%"))
    params.append(max(1, min(int(limit), 10)))

    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT source,source_type,repository,file_path,project,title,source_url,
                   content,visibility,scope,version_sha,content_hash,updated_at,last_ingested_at
            FROM knowledge_documents
            WHERE {' AND '.join(where)}
            ORDER BY ({relevance}) DESC, updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [
        {
            "source": r[0],
            "source_type": r[1],
            "repository": r[2],
            "file_path": r[3],
            "project": r[4],
            "title": r[5],
            "source_url": r[6],
            "content": r[7],
            "visibility": r[8],
            "scope": r[9],
            "version_sha": r[10],
            "content_hash": r[11],
            "updated_at": r[12],
            "last_ingested_at": r[13],
        }
        for r in rows
    ]
