from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from agents.executive_planner import ExecutivePlanner
from core.gatekeeper import inspect as inspect_input
from core.load_guard import load_guard
from core.memory_engine import get_or_create_session, recent_turns, save_turn, prune_old_sessions
from core.portfolio_store import retrieve_knowledge
from core.request_context import RequestContext
from core.security_policy import load_policy_bundle
from core.identity import authorize_bot_update, resolve_telegram_identity
from core.router import create_task
from core.semantic_memory import memory
from services.document_parser import extract_text
from services.security.guardrails import inspect as inspect_security
from services.security.permissions import inspect_request
from services.scheduler import scheduler
from tool_registry import execute as execute_tool, schemas
import nexo_tools

ENV_FILE = Path.home() / ".nexo.env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)
ADMIN_BOT_TOKEN = os.getenv("ADMIN_TELEGRAM_BOT_TOKEN", "").strip()
PUBLIC_BOT_TOKEN = os.getenv("PUBLIC_TELEGRAM_BOT_TOKEN", "").strip()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OWNER_RAW = (os.getenv("ADMIN_TELEGRAM_USER_ID", "").strip() or os.getenv("NEXO_OWNER_TELEGRAM_USER_ID", "").strip())
OWNER_TELEGRAM_USER_ID = int(OWNER_RAW) if OWNER_RAW.isdigit() else None
SYSTEM_FILE = Path(__file__).with_name("system_prompt.txt")
SYSTEM = load_policy_bundle()
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=[logging.FileHandler(LOG_DIR / "telegram.log", encoding="utf-8")])
logger = logging.getLogger("nexo.telegram")
planner: ExecutivePlanner | None = None
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_MEMORY_CHARS = 600
MAX_KNOWLEDGE_CHARS = 6000
MAX_TURNS_CHARS = 900
MAX_TURN_CHARS = 300
MAX_HISTORY_TURNS = 4
_CONTEXT_REFERENCES = ("this", "that", "it", "previous", "earlier", "before", "above", "continue", "again", "same", "we discussed", "you said", "as mentioned", "as discussed")
_MEMORY_HINTS = ("remember", "memory", "my name", "my preference", "my preferences", "my project", "my goal", "i told you", "you remember")
_KNOWLEDGE_HINTS = ("about", "repository", "repo", "project", "portfolio", "documentation", "docs", "codebase", "website", "file", "architecture", "readme", "github", "nexo", "alex")
MAX_UPDATE_QUEUE = 20
FAST_PATH_MESSAGES = {"hi", "hello", "hey", "hiya", "thanks", "thank you", "ok", "okay"}
app: Application | None = None


def is_owner(user_id: int) -> bool:
    return resolve_telegram_identity(user_id).is_admin


def _clip(text: str, limit: int) -> str:
    return (text or "")[:limit]


def _needs_history(goal: str) -> bool:
    text = (goal or "").casefold()
    return any(hint in text for hint in _CONTEXT_REFERENCES)


def _needs_memory(goal: str) -> bool:
    text = (goal or "").casefold()
    return any(hint in text for hint in _MEMORY_HINTS)


def _needs_knowledge(goal: str, intent: str | None = None) -> bool:
    text = (goal or "").casefold()
    return intent in {"coding", "research", "project", "portfolio"} or any(hint in text for hint in _KNOWLEDGE_HINTS)


def build_llm_messages(goal: str, turns: list[tuple[str, str]], memory_text: str, knowledge_text: str = "", *, include_history: bool = True, include_memory: bool = True, include_knowledge: bool = True) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]
    # Optional context is kept separate from the core system prompt. Place
    # policy-relevant memory/knowledge blocks before conversational history so
    # the core + optional system context has deterministic priority when fitting.
    if include_memory and memory_text.strip():
        messages.append({"role": "system", "content": "Relevant user memory:\n" + _clip(memory_text, MAX_MEMORY_CHARS)})
    if include_knowledge and knowledge_text.strip():
        messages.append({"role": "system", "content": "Authorized NEXO knowledge:\n" + _clip(knowledge_text, MAX_KNOWLEDGE_CHARS)})
    if include_history and turns:
        selected: list[tuple[str, str]] = []
        used = 0
        for role, content in reversed(turns[-MAX_HISTORY_TURNS:]):
            item = (role, _clip(content, MAX_TURN_CHARS))
            cost = len(item[1])
            if used + cost > MAX_TURNS_CHARS:
                continue
            selected.append(item)
            used += cost
        selected.reverse()
        messages.extend({"role": role, "content": content} for role, content in selected)
    messages.append({"role": "user", "content": goal})
    return messages


def _knowledge_text(docs: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    remaining = MAX_KNOWLEDGE_CHARS
    for doc in docs[:5]:
        content = _clip(str(doc.get("content") or ""), min(1800, remaining))
        if not content:
            continue
        parts.append(f"SOURCE={doc.get('source','')} PROJECT={doc.get('project','')} VISIBILITY={doc.get('visibility','')}\n{content}")
        remaining -= len(content)
        if remaining <= 0:
            break
    return "\n\n--- AUTHORIZED SOURCE ---\n".join(parts)


def _safe_failure_message() -> str:
    return "NEXO couldn't complete that request right now. The error has been logged."


async def typing_heartbeat(update: Update):
    try:
        while True:
            if update.message:
                await update.message.chat.send_action("typing")
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("typing indicator failed")


async def daily_briefing() -> None:
    if OWNER_TELEGRAM_USER_ID is None or app is None:
        return
    await app.bot.send_message(chat_id=OWNER_TELEGRAM_USER_ID, text="NEXO daily briefing: runtime scheduler is active. Use system_health for recent runtime errors.")


async def daily_maintenance() -> None:
    try:
        await asyncio.to_thread(prune_old_sessions)
    except Exception:
        logger.exception("scheduled session pruning failed")


async def handle_attachment(update: Update, user_id: int) -> str | None:
    message = update.message
    if not message:
        return None
    is_photo = bool(message.photo)
    item = message.document or (message.photo[-1] if is_photo else None)
    if not item:
        return None
    size = getattr(item, "file_size", None)
    if size is not None and size > MAX_ATTACHMENT_BYTES:
        return "That file is too large for this device. Please send a smaller file."
    file = await item.get_file()
    suffix = ".jpg" if is_photo else Path(getattr(item, "file_name", "attachment.bin") or "attachment.bin").suffix
    with tempfile.NamedTemporaryFile(prefix="nexo_", suffix=suffix, delete=False) as tmp:
        path = tmp.name
    try:
        await file.download_to_drive(path)
        parsed = await asyncio.to_thread(extract_text, path)
        if not parsed.get("ok"):
            logger.warning("attachment_parse_failed user_id=%s category=%s", user_id, type(parsed.get("error"),).__name__)
            return "I received the file, but local parsing is unavailable right now."
        text = parsed.get("text", "")
        if text:
            if not memory.add(text[:12000], "document", 4, "telegram_attachment", user_id=user_id):
                return "File parsed locally, but the extracted content was not eligible for long-term memory."
            return "File parsed locally and useful extracted text was added to semantic memory."
        return "File received, but no text could be extracted locally."
    finally:
        Path(path).unlink(missing_ok=True)


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_role: str = "public"):
    global planner
    if not update.message:
        return
    user = update.effective_user
    if user is None:
        return
    if not authorize_bot_update(bot_role, user.id):
        await update.message.reply_text("Sorry, I can't help with that.")
        return
    admitted, reason = await load_guard.acquire(user.id)
    if not admitted:
        messages = {"rate_limited": "Please wait a moment before sending another request.", "overloaded": "NEXO is busy right now. Please try again shortly.", "queue_timeout": "NEXO is under heavy load. Please try again shortly."}
        await update.message.reply_text(messages.get(reason, "NEXO is temporarily busy. Please try again shortly."))
        return
    typing_task = asyncio.create_task(typing_heartbeat(update))
    try:
        identity = resolve_telegram_identity(user.id)
        request_context = RequestContext.telegram(user.id, identity.role)
        attachment_result = await handle_attachment(update, user.id)
        if attachment_result:
            await update.message.reply_text(attachment_result)
            return
        text = (update.message.text or "").strip()
        if not text:
            return
        gate = inspect_input(text)
        if not gate.get("allow"):
            await update.message.reply_text("I can't process that request.")
            return
        security = inspect_security(text)
        if not security.get("safe"):
            await update.message.reply_text("I can't process that request because it contains restricted information or an unsafe action.")
            return
        policy = inspect_request(text, user.id, OWNER_TELEGRAM_USER_ID)
        if not policy["safe"]:
            await update.message.reply_text("I can't treat that request as trusted instructions.")
            return
        if text.casefold() in FAST_PATH_MESSAGES:
            fast_replies = {"hi": "Hi! How can I help?", "hello": "Hello! How can I help?", "hey": "Hey! How can I help?", "hiya": "Hi! How can I help?", "thanks": "You're welcome!", "thank you": "You're welcome!", "ok": "Okay.", "okay": "Okay."}
            answer = fast_replies[text.casefold()]
            session_id = get_or_create_session(user.id)
            save_turn(session_id, user.id, "user", text)
            save_turn(session_id, user.id, "assistant", answer)
            await update.message.reply_text(answer)
            return

        manager_task = create_task(text)
        if manager_task.intent == "out_of_scope":
            await update.message.reply_text("I can't process that request in the current NEXO scope.")
            return
        session_id = get_or_create_session(user.id)
        wants_history = _needs_history(text)
        wants_memory = _needs_memory(text)
        wants_knowledge = _needs_knowledge(text, manager_task.intent)

        turns = recent_turns(session_id, limit=MAX_HISTORY_TURNS) if wants_history else []
        memories = memory.search(text, limit=4, user_id=user.id) if wants_memory else []
        memory_text = "\n".join(x["content"] for x in memories)
        knowledge = retrieve_knowledge(text, channel=request_context.channel, scope=request_context.scope, limit=5) if wants_knowledge else []
        knowledge_text = _knowledge_text(knowledge)
        messages = build_llm_messages(text, turns, memory_text, knowledge_text, include_history=wants_history, include_memory=wants_memory, include_knowledge=wants_knowledge)
        tool_set = [] if manager_task.intent == "conversation" else schemas(include_owner_only=identity.is_admin)
        logger.info("context_selection user_id=%s intent=%s history=%s memory=%s knowledge=%s history_candidates=%d", user.id, manager_task.intent, wants_history, wants_memory, wants_knowledge, len(turns))
        planner = planner or ExecutivePlanner()
        answer = await asyncio.to_thread(planner.run, text, messages, tool_set, execute_tool, owner=identity.is_admin, user_id=user.id, max_steps=1 if not tool_set else 6, intent=manager_task.intent)
        answer = answer.strip()
        if not answer:
            raise RuntimeError("empty_model_response")
        save_turn(session_id, user.id, "user", text)
        save_turn(session_id, user.id, "assistant", answer)
        await update.message.reply_text(answer[:4000])
    except RuntimeError as exc:
        logger.exception("NEXO pipeline failure category=%s user_id=%s", str(exc), user.id)
        if str(exc).startswith(("context_budget_exceeded_user_message_too_large", "context_budget_insufficient")):
            await update.message.reply_text("That message is too large for NEXO's current context budget. Please send a shorter request.")
        else:
            await update.message.reply_text(_safe_failure_message())
    except Exception:
        logger.exception("Telegram request failed for user_id=%s", user.id)
        await update.message.reply_text(_safe_failure_message())
    finally:
        typing_task.cancel()
        await load_guard.release()

async def _post_init(application: Application) -> None:
    del application
    scheduler.start(daily_briefing, daily_maintenance)
    logger.info("NEXO Telegram scheduler started")


async def _post_shutdown(application: Application) -> None:
    del application
    scheduler.stop()
    logger.info("NEXO Telegram scheduler stopped")


def _build_application(token: str, bot_role: str) -> Application:
    application = (
        Application.builder()
        .token(token)
        .concurrent_updates(False)
        .update_queue(asyncio.Queue(maxsize=MAX_UPDATE_QUEUE))
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda update, context: chat(update, context, bot_role)))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, lambda update, context: chat(update, context, bot_role)))
    return application


async def _run_bots() -> None:
    global app
    if not ADMIN_BOT_TOKEN or not PUBLIC_BOT_TOKEN:
        raise RuntimeError("ADMIN_TELEGRAM_BOT_TOKEN and PUBLIC_TELEGRAM_BOT_TOKEN are required")
    admin = _build_application(ADMIN_BOT_TOKEN, "admin")
    public = _build_application(PUBLIC_BOT_TOKEN, "public")
    app = admin
    applications = (admin, public)
    try:
        for application in applications:
            await application.initialize()
            await application.start()
            await application.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()
    finally:
        scheduler.stop()
        for application in reversed(applications):
            if application.updater and application.updater.running:
                await application.updater.stop()
            if application.running:
                await application.stop()
            await application.shutdown()


def main() -> None:
    if ADMIN_BOT_TOKEN and PUBLIC_BOT_TOKEN:
        asyncio.run(_run_bots())
        return
    global app
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    app = (
        Application.builder()
        .token(TOKEN)
        .concurrent_updates(False)
        .update_queue(asyncio.Queue(maxsize=MAX_UPDATE_QUEUE))
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, chat))
    logger.info("NEXO unified Telegram runtime starting with hosted LLM provider")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
