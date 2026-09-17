from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "memory.db"
STATUSES = {"pending", "accepted", "failed", "needs_review"}
APPROVAL_STATUSES = {"pending", "approved", "rejected"}


@contextmanager
def _connect(db_path: Path | str = DB):
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS evaluations("
        "request_id TEXT PRIMARY KEY, channel TEXT NOT NULL, user_id TEXT, session_id TEXT, "
        "response TEXT NOT NULL, status TEXT NOT NULL, feedback TEXT NOT NULL DEFAULT '', "
        "correction_candidate TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'interaction', "
        "approval_status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_channel_created ON evaluations(channel, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_status ON evaluations(status, approval_status, created_at DESC)")


def ensure_schema(db_path: Path | str = DB) -> None:
    with _connect(db_path) as conn:
        _ensure_schema(conn)


def record_evaluation(*, request_id: str, channel: str, response: str, user_id: str | None = None, session_id: str | None = None, status: str = "pending", feedback: str = "", correction_candidate: str = "", source: str = "interaction", db_path: Path | str = DB) -> bool:
    if not request_id or not channel or not response or status not in STATUSES:
        return False
    if len(response) > 12000 or len(feedback) > 12000 or len(correction_candidate) > 12000:
        return False
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _connect(db_path) as conn:
            _ensure_schema(conn)
            conn.execute(
                "INSERT INTO evaluations(request_id,channel,user_id,session_id,response,status,feedback,correction_candidate,source,approval_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (request_id, channel, user_id, session_id, response, status, feedback, correction_candidate, source, "pending", now, now),
            )
        return True
    except sqlite3.Error:
        return False


def update_evaluation(request_id: str, *, status: str | None = None, feedback: str | None = None, correction_candidate: str | None = None, approval_status: str | None = None, db_path: Path | str = DB) -> bool:
    if not request_id or (status is not None and status not in STATUSES) or (approval_status is not None and approval_status not in APPROVAL_STATUSES):
        return False
    fields: list[str] = []
    values: list[Any] = []
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if feedback is not None:
        if len(feedback) > 12000:
            return False
        fields.append("feedback=?")
        values.append(feedback)
    if correction_candidate is not None:
        if len(correction_candidate) > 12000:
            return False
        fields.append("correction_candidate=?")
        values.append(correction_candidate)
    if approval_status is not None:
        fields.append("approval_status=?")
        values.append(approval_status)
    if not fields:
        return False
    fields.append("updated_at=?")
    values.append(datetime.now(timezone.utc).isoformat())
    values.append(request_id)
    try:
        with _connect(db_path) as conn:
            _ensure_schema(conn)
            cur = conn.execute(f"UPDATE evaluations SET {', '.join(fields)} WHERE request_id=?", values)
            return cur.rowcount == 1
    except sqlite3.Error:
        return False


def get_evaluation(request_id: str, db_path: Path | str = DB) -> dict[str, Any] | None:
    if not request_id:
        return None
    try:
        with _connect(db_path) as conn:
            _ensure_schema(conn)
            row = conn.execute("SELECT request_id,channel,user_id,session_id,response,status,feedback,correction_candidate,source,approval_status,created_at,updated_at FROM evaluations WHERE request_id=?", (request_id,)).fetchone()
        if not row:
            return None
        keys = ("request_id", "channel", "user_id", "session_id", "response", "status", "feedback", "correction_candidate", "source", "approval_status", "created_at", "updated_at")
        return dict(zip(keys, row))
    except sqlite3.Error:
        return None
