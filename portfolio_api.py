from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ENV_FILE = Path.home() / ".nexo.env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)

from core.portfolio_store import ensure_schema, new_session_id
from core.request_context import RequestContext
from services.portfolio_ai import portfolio_ai
from services.public_knowledge_refresh import refresh_public_knowledge

APP_NAME = "NEXO Portfolio AI API"
COOKIE = "nexo_portfolio_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_RATE_LIMIT = 20
DEFAULT_RATE_WINDOW_SECONDS = 60
MAX_RATE_KEYS = 10000

app = FastAPI(title=APP_NAME, version="1.1")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, *, limit: int, window_seconds: int, now: float | None = None) -> bool:
        if not key:
            return False
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > MAX_RATE_KEYS:
                cutoff = now - window_seconds
                for item in list(self._hits):
                    bucket = self._hits[item]
                    while bucket and bucket[0] <= cutoff:
                        bucket.popleft()
                    if not bucket:
                        del self._hits[item]
                    if len(self._hits) <= MAX_RATE_KEYS:
                        break
            bucket = self._hits.setdefault(key, deque())
            cutoff = now - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


rate_limiter = SlidingWindowRateLimiter()


def _allowed_origins() -> tuple[str, ...]:
    return tuple(x.strip() for x in os.getenv("NEXO_PORTFOLIO_ALLOWED_ORIGINS", "").split(",") if x.strip())


def _session_secret() -> str:
    return os.getenv("NEXO_PORTFOLIO_SESSION_SECRET", "").strip()


def _rate_limit() -> tuple[int, int]:
    try:
        limit = max(1, min(int(os.getenv("NEXO_PORTFOLIO_RATE_LIMIT", str(DEFAULT_RATE_LIMIT))), 120))
    except (TypeError, ValueError):
        limit = DEFAULT_RATE_LIMIT
    try:
        window = max(1, min(int(os.getenv("NEXO_PORTFOLIO_RATE_WINDOW_SECONDS", str(DEFAULT_RATE_WINDOW_SECONDS))), 3600))
    except (TypeError, ValueError):
        window = DEFAULT_RATE_WINDOW_SECONDS
    return limit, window


def _origin_allowed(origin: str | None) -> bool:
    origins = _allowed_origins()
    if not origin:
        return True
    return origin in origins


def _require_public_origin(origin: str | None) -> None:
    if not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="origin_not_allowed")


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _encode_session(session_id: str, expires_at: int, secret: str) -> str:
    payload = f"{session_id}.{expires_at}"
    return f"{payload}.{_sign(payload, secret)}"


def _decode_session(cookie: str | None) -> str | None:
    secret = _session_secret()
    if not secret or not cookie:
        return None
    parts = cookie.split(".")
    if len(parts) != 3:
        return None
    session_id, raw_exp, provided = parts
    if not session_id or not raw_exp or not provided:
        return None
    try:
        expires_at = int(raw_exp)
    except ValueError:
        return None
    if expires_at <= int(time.time()):
        return None
    payload = f"{session_id}.{expires_at}"
    expected = _sign(payload, secret)
    if not hmac.compare_digest(provided, expected):
        return None
    if not 32 <= len(session_id) <= 128:
        return None
    return session_id


def _session(response: Response, cookie: str | None) -> str:
    secret = _session_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="portfolio_session_not_configured")
    existing = _decode_session(cookie)
    if existing:
        return existing
    session_id = new_session_id()
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    response.set_cookie(
        COOKIE,
        _encode_session(session_id, expires_at, secret),
        httponly=True,
        secure=os.getenv("NEXO_PORTFOLIO_COOKIE_SECURE", "true").strip().lower() in {"1", "true", "yes", "on"},
        samesite="none" if os.getenv("NEXO_PORTFOLIO_COOKIE_SECURE", "true").strip().lower() in {"1", "true", "yes", "on"} else "lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )
    return session_id


def _client_key(request: Request, session_id: str) -> str:
    # Prefer the authenticated-by-signature session; IP is only an additional
    # bucket so a single client cannot exhaust one session and rotate endlessly.
    host = request.client.host if request.client else "unknown"
    return f"{host}:{session_id}"


def _check_rate_limit(request: Request, session_id: str) -> None:
    limit, window = _rate_limit()
    if not rate_limiter.allow(_client_key(request, session_id), limit=limit, window_seconds=window):
        raise HTTPException(status_code=429, detail="rate_limited", headers={"Retry-After": str(window)})


if _allowed_origins():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_allowed_origins()),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )


@app.on_event("startup")
def startup() -> None:
    ensure_schema()
    if os.getenv("NEXO_PUBLIC_KNOWLEDGE_REFRESH_ON_STARTUP", "true").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            refresh_public_knowledge()
        except Exception:
            # A remote knowledge refresh must never prevent the API from starting.
            pass


@app.get("/api/portfolio/session")
def create_session(
    request: Request,
    response: Response,
    origin: str | None = Header(default=None),
) -> dict[str, str]:
    _require_public_origin(origin)
    session_id = _session(response, None)
    _check_rate_limit(request, session_id)
    return {"scope": "public_portfolio", "channel": "portfolio_web", "session": "created"}


@app.post("/api/portfolio/chat")
def chat(
    request: Request,
    payload: ChatRequest,
    response: Response,
    origin: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, str]:
    _require_public_origin(origin)
    session_id = _session(response, session_cookie)
    _check_rate_limit(request, session_id)
    context = RequestContext.portfolio(session_id)
    return portfolio_ai.answer(payload.message, context)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "nexo-portfolio-ai"}
