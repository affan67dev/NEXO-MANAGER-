from __future__ import annotations

import asyncio
import json
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
from core.memory_engine import get_or_create_session, recent_turns, save_turn, prune_old_sessions
from core.semantic_memory import memory
from services.document_parser import extract_text
from services.security.guardrails import inspect as inspect_security
from services.security.permissions import inspect_request
from services.scheduler import scheduler
from tool_registry import execute as execute_tool, schemas
import nexo_tools  # registers tools

ENV_FILE = Path.home() / ".nexo.env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
LLAMA_URL = os.getenv("LLAMA_URL", "http://127.0.0.1:8080/v1/chat/completions").strip()
OWNER_RAW = os.getenv("NEXO_OWNER_TELEGRAM_USER_ID", "").strip()
OWNER_TELEGRAM_USER_ID = int(OWNER_RAW) if OWNER_RAW.isdigit() else None
SYSTEM_FILE = Path(__file__).with_name("system_prompt.txt")
SYSTEM = SYSTEM_FILE.read_text(encoding="utf-8") if SYSTEM_FILE.exists() else "You are NEXO, a safe local-first personal AI executive assistant."
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=[logging.FileHandler(LOG_DIR / "telegram.log", encoding="utf-8")])
logger = logging.getLogger("nexo.telegram")
busy: set[int] = set()
planner = ExecutivePlanner(LLAMA_URL)

def is_owner(user_id: int) -> bool:
    return OWNER_TELEGRAM_USER_ID is not None and user_id == OWNER_TELEGRAM_USER_ID

async def typing_heartbeat(update: Update):
    try:
        while True:
            await update.message.chat.send_action("typing")
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("typing indicator failed")

async def daily_briefing() -> None:
    if OWNER_TELEGRAM_USER_ID is None:
        return
    await app.bot.send_message(chat_id=OWNER_TELEGRAM_USER_ID, text="NEXO daily briefing: runtime scheduler is active. Use system_health for recent runtime errors.")

async def handle_attachment(update: Update) -> str | None:
    message = update.message
    if not message:
        return None
    item = message.document or (message.photo[-1] if message.photo else None)
    if not item:
        return None
    file = await item.get_file()
    suffix = Path(getattr(item, "file_name", "attachment.bin") or "attachment.bin").suffix
    with tempfile.NamedTemporaryFile(prefix="nexo_", suffix=suffix, delete=False) as tmp:
        path = tmp.name
    try:
        await file.download_to_drive(path)
        parsed = await asyncio.to_thread(extract_text, path)
        if not parsed.get("ok"):
            return f"I received the file, but local parsing is unavailable: {parsed.get('error','unknown_error')}"
        text = parsed.get("text", "")
        if text:
            memory.add(text[:12000], "document", 4, "telegram_attachment")
        return "File parsed locally and useful extracted text was added to semantic memory." if text else "File received, but no text could be extracted locally."
    finally:
        Path(path).unlink(missing_ok=True)

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    if user is None:
        return
    attachment_result = await handle_attachment(update)
    if attachment_result:
        await update.message.reply_text(attachment_result)
        return
    text = (update.message.text or "").strip()
    if not text or user.id in busy:
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
    busy.add(user.id)
    typing_task = asyncio.create_task(typing_heartbeat(update))
    try:
        session_id = get_or_create_session(user.id)
        turns = recent_turns(session_id, limit=8)
        memories = memory.search(text, limit=4)
        memory_text = "\n".join(x["content"] for x in memories) or "(none; use web_search when external/current information is required)"
        messages: list[dict[str, Any]] = [{"role":"system","content":SYSTEM + "\n\nRelevant long-term memory:\n" + memory_text}]
        messages.extend({"role": role, "content": content} for role, content in turns)
        answer = await asyncio.to_thread(planner.run, text, messages, schemas(), execute_tool, owner=is_owner(user.id), max_steps=6)
        save_turn(session_id, user.id, "user", text)
        save_turn(session_id, user.id, "assistant", answer)
        await update.message.reply_text(answer[:4000])
    except Exception:
        logger.exception("Telegram request failed for user_id=%s", user.id)
        await update.message.reply_text("Sorry, I couldn't complete that request right now.")
    finally:
        typing_task.cancel()
        busy.discard(user.id)
        try:
            prune_old_sessions()
        except Exception:
            logger.exception("session pruning failed")

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

app = Application.builder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, chat))
scheduler.start(daily_briefing)
logger.info("NEXO unified Telegram runtime starting")
app.run_polling(drop_pending_updates=True)
