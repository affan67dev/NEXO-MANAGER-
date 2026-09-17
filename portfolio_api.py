from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Portfolio API is a separate Uvicorn entrypoint from Telegram. Load the same
# server-side environment file before lazy provider creation can occur.
ENV_FILE = Path.home() / ".nexo.env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)

from core.evaluation import update_evaluation
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
    message: str = Field(min_length=1, max_length=4000)


class V1ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, min_length=32, max_length=128)
    client: Literal["portfolio"] = "portfolio"


class FeedbackRequest(BaseModel):
    request_id: str = Field(min_length=16, max_length=128)
    status: Literal["accepted", "failed", "needs_review"]
    feedback: str = Field(default="", max_length=4000)
    correction_candidate: str = Field(default="", max_length=12000)


def _origin_allowed(origin: str | None) -> bool:
    return bool(origin and origin in MAX_ORIGINS)


def _session(response: Response, cookie: str | None) -> str:
    if cookie and 32 <= len(cookie) <= 128:
        return cookie
    session_id = new_session_id()
    response.set_cookie(COOKIE, session_id, httponly=True, secure=COOKIE_SECURE, samesite="none" if COOKIE_SECURE else "lax", max_age=7 * 24 * 60 * 60, path="/")
    return session_id


def _check_origin(origin: str | None) -> None:
    if MAX_ORIGINS and not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="origin_not_allowed")


@app.on_event("startup")
def startup() -> None:
    ensure_schema()


@app.get("/api/portfolio/session")
def create_session(response: Response, origin: str | None = Header(default=None)) -> dict[str, str]:
    _check_origin(origin)
    _session(response, None)
    return {"scope": "public_portfolio", "channel": "portfolio_web", "session": "created"}


def _chat_impl(request: ChatRequest, response: Response, origin: str | None, session_cookie: str | None) -> dict[str, str]:
    _check_origin(origin)
    session_id = _session(response, session_cookie)
    context = RequestContext.portfolio(session_id, uuid4().hex)
    return portfolio_ai.answer(request.message, context)


@app.post("/api/portfolio/chat")
def chat(request: ChatRequest, response: Response, origin: str | None = Header(default=None), session_cookie: str | None = Cookie(default=None, alias=COOKIE)) -> dict[str, str]:
    return _chat_impl(request, response, origin, session_cookie)


@app.post("/api/v1/ai/chat")
def v1_chat(request: V1ChatRequest, response: Response, origin: str | None = Header(default=None), session_cookie: str | None = Cookie(default=None, alias=COOKIE)) -> dict[str, str]:
    """Versioned public Portfolio adapter. Body session_id is validated but never trusted for authorization."""
    result = _chat_impl(ChatRequest(message=request.message), response, origin, session_cookie)
    return {
        "answer": result.get("answer", ""),
        "action": result.get("action", "answer"),
        "request_id": result.get("request_id", ""),
        "status": result.get("status", "error"),
    }


@app.post("/api/v1/ai/feedback")
def v1_feedback(request: FeedbackRequest, origin: str | None = Header(default=None)) -> dict[str, str | bool]:
    """Record explicit evaluation without allowing feedback to mutate memory or knowledge."""
    _check_origin(origin)
    updated = update_evaluation(
        request.request_id,
        status=request.status,
        feedback=request.feedback,
        correction_candidate=request.correction_candidate,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="evaluation_not_found")
    return {"ok": True, "request_id": request.request_id, "status": request.status}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "nexo-portfolio-ai"}
