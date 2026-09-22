from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import time

from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Portfolio API is a separate Uvicorn entrypoint from Telegram. Load the same
# server-side environment file before lazy provider creation can occur.
ENV_FILE = Path.home() / ".nexo.env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)

from core.portfolio_store import ensure_schema, new_session_id
from core.request_context import RequestContext
from services.portfolio_ai import portfolio_ai
from services.public_knowledge_refresh import refresh_public_knowledge

APP_NAME = "NEXO Portfolio AI API"
COOKIE = "nexo_portfolio_session"
MAX_ORIGINS = tuple(x.strip() for x in os.getenv("NEXO_PORTFOLIO_ALLOWED_ORIGINS", "").split(",") if x.strip())
COOKIE_SECURE = os.getenv("NEXO_PORTFOLIO_COOKIE_SECURE", "true").strip().lower() in {"1", "true", "yes", "on"}
SESSION_SECRET = os.getenv("NEXO_PORTFOLIO_SESSION_SECRET", "").strip()
if not SESSION_SECRET:
    # Safe for local/dev use; production should provide a stable server-side secret.
    SESSION_SECRET = secrets.token_hex(32)

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 20
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)

app = FastAPI(title=APP_NAME, version="1.0")
if MAX_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(MAX_ORIGINS),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


def _origin_allowed(origin: str | None) -> bool:
    return bool(MAX_ORIGINS and origin and origin in MAX_ORIGINS)


def _sign_session(session_id: str) -> str:
    digest = hmac.new(SESSION_SECRET.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{session_id}.{digest}"


def _verify_session(cookie: str | None) -> str | None:
    if not cookie or "." not in cookie:
        return None
    session_id, signature = cookie.rsplit(".", 1)
    if not (32 <= len(session_id) <= 128 and len(signature) == 64):
        return None
    expected = _sign_session(session_id).rsplit(".", 1)[1]
    if not hmac.compare_digest(signature, expected):
        return None
    return session_id


def _set_session(response: Response, session_id: str) -> None:
    response.set_cookie(
        COOKIE,
        _sign_session(session_id),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="none" if COOKIE_SECURE else "lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )


def _session(response: Response, cookie: str | None) -> str:
    session_id = _verify_session(cookie)
    if session_id:
        return session_id
    session_id = new_session_id()
    _set_session(response, session_id)
    return session_id


def _rate_key(request: Request, session_cookie: str | None) -> str:
    # Do not trust forwarded client-IP headers here; the deployment proxy is not
    # configured as a trusted proxy boundary by this application.
    client_host = request.client.host if request.client else "unknown"
    session_id = _verify_session(session_cookie) or "anonymous"
    return f"{client_host}:{session_id}"


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    bucket = _rate_buckets[key]
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(status_code=429, detail="rate_limited")
    bucket.append(now)


def _require_origin(origin: str | None) -> None:
    # An empty allowlist is treated as a deployment misconfiguration, not as
    # permission to accept credentialed browser requests from arbitrary origins.
    if not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="origin_not_allowed")


@app.on_event("startup")
def startup() -> None:
    ensure_schema()
    if os.getenv("NEXO_PUBLIC_KNOWLEDGE_REFRESH_ON_STARTUP", "true").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            refresh_public_knowledge()
        except Exception:
            # Knowledge refresh must never prevent the public API from starting.
            pass


@app.get("/api/portfolio/session")
def create_session(
    request: Request,
    response: Response,
    origin: str | None = Header(default=None),
) -> dict[str, str]:
    _require_origin(origin)
    _check_rate_limit(_rate_key(request, None))
    session_id = new_session_id()
    _set_session(response, session_id)
    return {"scope": "public_portfolio", "channel": "portfolio_web", "session": "created"}


@app.post("/api/portfolio/chat")
def chat(
    request: ChatRequest,
    http_request: Request,
    response: Response,
    origin: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=COOKIE),
) -> dict[str, str]:
    _require_origin(origin)
    _check_rate_limit(_rate_key(http_request, session_cookie))
    session_id = _session(response, session_cookie)
    context = RequestContext.portfolio(session_id)
    return portfolio_ai.answer(request.message, context)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "nexo-portfolio-ai"}
