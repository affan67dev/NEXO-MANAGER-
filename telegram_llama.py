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
ADMIN_BOT_TOKEN = os.getenv("ADMIN_TELEGRAM_BOT_TOKEN", "").strip()\nPUBLIC_BOT_TOKEN = os.getenv("PUBLIC_TELEGRAM_BOT_TOKEN", "").strip()
OWNER_RAW = os.getenv("NEXO_OWNER_TELEGRAM_USER_ID", "").strip()
OWNER_TELEGRAM_USER_ID = int(OWNER_RAW) if OWNER_RAW.isdigit() else None
SYSTEM_FILE = Path(__file__).with_name("system_prompt.txt")
SYSTEM = SYSTEM_FILE.read_text(encoding="utf-8") if SYSTEM_FILE.exists() else "You are NEXO, a safe personal AI executive assistant."
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
MAX_UPDATE_QUEUE = 20
FAST_PATH_MESSAGES = {"hi", "hello", "hey", "hiya", "thanks", "thank you", "ok", "okay"}
admin_app: Application | None = None


def is_owner(user_id: int) -> bool:
    return resolve_telegram_identity(user_id).is_admin


def _clip(text: str, limit: int) -> str:
    return (text or "")[:limit]


def build_llm_messages(goal: str, turns: list[tuple[str, str]], memory_text: str, knowledge_text: str = "") -> list[dict[str, str]]:
    system = SYSTEM
    system += "\n\nRelevant user memory:\n" + _clip(memory_text, MAX_MEMORY_CHARS)
    if knowledge_text:
        system += "\n\nAuthorized NEXO knowledge:\n" + _clip(knowledge_text, MAX_KNOWLEDGE_CHARS)
    selected: list[tuple[str, str]] = []
    used = 0
    for role, content in reversed(turns):
        item = (role, _clip(content, MAX_TURN_CHARS))
        cost = len(item[1])
        if used + cost > MAX_TURNS_CHARS:
            continue
        selected.append(item)
        used += cost
    selected.reverse()
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
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
    if OWNER_TELEGRAM_USER_ID is None or admin_app is None:
        return
    await admin_app.bot.send_message(chat_id=OWNER_TELEGRAM_USER_ID, text="NEXO daily briefing: runtime scheduler is active. Use system_health for recent runtime errors.")


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


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_role: str):
    global planner
    if not update.message:
        return
    user = update.effective_user
    if user is None:
        return
    if not authorize_bot_update(bot_role, user.id):\n        await update.message.reply_text(_unauthorized_message())\n        return\n    admitted, reason = await load_guard.acquire(user.id)
    if not admitted:
        messages = {"rate_limited": "Please wait a moment before sending another request.", "overloaded": "NEXO is busy right now. Please try again shortly.", "queue_timeout": "NEXO is under heavy load. Please try again shortly."}
        await update.message.reply_text(messages.get(reason, "NEXO is temporarily busy. Please try again shortly."))
        return
    typing_task = asyncio.create_task(typing_heartbeat(update))
    try:
        identity = resolve_telegram_identity(user.id)
        request_context = RequestContext.telegram(user.id)
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
        turns = recent_turns(session_id, limit=8)
        memories = memory.search(text, limit=4, user_id=user.id)
        memory_text = "\n".join(x["content"] for x in memories) or "(none)"
        knowledge = retrieve_knowledge(text, channel=request_context.channel, scope=request_context.scope, limit=5)
        knowledge_text = _knowledge_text(knowledge)
        messages = build_llm_messages(text, turns, memory_text, knowledge_text)
        tool_set = [] if manager_task.intent == "conversation" else schemas(include_owner_only=identity.is_admin)
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
        if str(exc).startswith("context_budget_exceeded_user_message_too_large"):
            await update.message.reply_text("That message is too large for NEXO's current context budget. Please send a shorter request.")
        else:
            await update.message.reply_text(_safe_failure_message())
    except Exception:
        logger.exception("Telegram request failed for user_id=%s", user.id)
        await update.message.reply_text(_safe_failure_message())
    finally:
        typing_task.cancel()
        await load_guard.release()


def _build_application(token: str, bot_role: str) -> Application:
    application = (Application.builder().token(token).concurrent_updates(False).update_queue(asyncio.Queue(maxsize=MAX_UPDATE_QUEUE)).build())
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda update, context: chat(update, context, bot_role)))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, lambda update, context: chat(update, context, bot_role)))
    return application


async def _run_bots() -> None:
    global admin_app
    if not ADMIN_BOT_TOKEN:
        raise RuntimeError("ADMIN_TELEGRAM_BOT_TOKEN is not configured")
    if not PUBLIC_BOT_TOKEN:
        raise RuntimeError("PUBLIC_TELEGRAM_BOT_TOKEN is not configured")

    admin_app = _build_application(ADMIN_BOT_TOKEN, "admin")
    public_app = _build_application(PUBLIC_BOT_TOKEN, "public")
    applications = (admin_app, public_app)
    try:
        for application in applications:
            await application.initialize()
        for application in applications:
            await application.start()
        for application in applications:
            await application.updater.start_polling(drop_pending_updates=True)
        scheduler.start(daily_briefing, daily_maintenance)
        logger.info("NEXO Telegram runtime started with separate admin and public bots")
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
    asyncio.run(_run_bots())


if __name__ == "__main__":
    main()
