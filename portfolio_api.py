from __future__ import annotations

import os
from typing import Annotated

from fastapi import Cookie, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.portfolio_store import ensure_schema, new_session_id
from core.request_context import RequestContext
from services.portfolio_ai import portfolio_ai

APP_NAME = "NEXO Portfolio AI API"
COOKIE = "nexo_portfolio_session"
MAX_ORIGINS = tuple(x.strip() for x in os.getenv("NEXO_PORTFOLIO_ALLOWED_ORIGINS", "").split(",") if x.strip())
COOKIE_SECURE = os.getenv("NEXO_PORTFOLIO_COOKIE_SECURE", "true").strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(title=APP_NAME, version="1.0")
if MAX_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=list(MAX_ORIGINS), allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


class ChatRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=4000)]


def _origin_allowed(origin: str | None) -> bool:
    return bool(origin and origin in MAX_ORIGINS)


def _session(response: Response, cookie: str | None) -> str:
    if cookie and 32 <= len(cookie) <= 128:
        return cookie
    session_id = new_session_id()
    response.set_cookie(COOKIE, session_id, httponly=True, secure=COOKIE_SECURE, samesite="none" if COOKIE_SECURE else "lax", max_age=7 * 24 * 60 * 60, path="/")
    return session_id


@app.on_event("startup")
def startup() -> None:
    ensure_schema()


@app.get("/api/portfolio/session")
def create_session(response: Response, origin: str | None = Header(default=None)) -> dict[str, str]:
    if MAX_ORIGINS and not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="origin_not_allowed")
    _session(response, None)
    return {"scope": "public_portfolio", "channel": "portfolio_web", "session": "created"}


@app.post("/api/portfolio/chat")
def chat(request: ChatRequest, response: Response, origin: str | None = Header(default=None), session_cookie: str | None = Cookie(default=None, alias=COOKIE)) -> dict[str, str]:
    if MAX_ORIGINS and not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="origin_not_allowed")
    session_id = _session(response, session_cookie)
    context = RequestContext.portfolio(session_id)
    return portfolio_ai.answer(request.message, context)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "nexo-portfolio-ai"}
