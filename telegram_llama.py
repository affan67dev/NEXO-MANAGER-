import os
import json
import urllib.request
import asyncio
import subprocess

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

import app_router
from core.gatekeeper import inspect as inspect_input
from services.security.guardrails import inspect as inspect_security
from core.memory_engine import get_or_create_session, recent_turns, save_turn, save_memory

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
LLAMA_URL = os.getenv("LLAMA_URL", "http://127.0.0.1:8080/v1/chat/completions")
ALLOWED_TELEGRAM_USER_IDS = {
    int(x.strip()) for x in os.getenv("NEXO_ALLOWED_TELEGRAM_USER_IDS", "").split(",")
    if x.strip().isdigit()
}

SYSTEM_FILE = os.path.expanduser("~/NEXO/system_prompt.txt")
SYSTEM = (
    open(SYSTEM_FILE, encoding="utf-8").read()
    if os.path.exists(SYSTEM_FILE)
    else "You are NEXO, a safe personal application-operations assistant."
)

busy = set()


def authorized(user_id: int) -> bool:
    return bool(ALLOWED_TELEGRAM_USER_IDS) and user_id in ALLOWED_TELEGRAM_USER_IDS


def run_command(command, timeout=15):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:
        return None


def fast_tool(text):
    t = text.lower().strip()

    try:
        result = app_router.execute(text)
        if isinstance(result, dict) and result.get("ok"):
            action = result.get("command", {}).get("action")
            if action in ("open", "search"):
                # termux-open-url has no reliable foreground-state verification.
                # Therefore this is deliberately reported as dispatched, not verified.
                return result.get("message", "Command dispatched."), False
    except Exception:
        pass

    if any(x in t for x in ["wifi on", "wi-fi on", "wifi चालू", "वाईफाई चालू"]):
        p = run_command(["termux-wifi-enable", "true"])
        return ("Wi-Fi command completed." if p and p.returncode == 0 else "Wi-Fi action failed."), bool(p and p.returncode == 0)

    if any(x in t for x in ["wifi off", "wi-fi off", "wifi बंद", "वाईफाई बंद"]):
        p = run_command(["termux-wifi-enable", "false"])
        return ("Wi-Fi command completed." if p and p.returncode == 0 else "Wi-Fi action failed."), bool(p and p.returncode == 0)

    if any(x in t for x in ["flashlight on", "torch on", "flash on", "flashlight चालू", "torch चालू"]):
        p = run_command(["termux-torch", "on"])
        return ("Flashlight command completed." if p and p.returncode == 0 else "Flashlight action failed."), bool(p and p.returncode == 0)

    if any(x in t for x in ["flashlight off", "torch off", "flash off", "flashlight बंद", "torch बंद"]):
        p = run_command(["termux-torch", "off"])
        return ("Flashlight command completed." if p and p.returncode == 0 else "Flashlight action failed."), bool(p and p.returncode == 0)

    if any(x in t for x in ["battery status", "battery level", "battery कितनी", "बैटरी"]):
        p = run_command(["termux-battery-status"])
        if p and p.returncode == 0:
            try:
                b = json.loads(p.stdout)
                return f"Battery: {b.get('percentage', '?')}% | Status: {b.get('status', '?')} | Temperature: {b.get('temperature', '?')}°C", True
            except Exception:
                return p.stdout.strip() or "Battery status unavailable.", False
        return "Battery status failed.", False

    return None


def ask_llama(messages):
    data = json.dumps({
        "messages": messages,
        "temperature": 0.15,
        "max_tokens": 256,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        LLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        result = json.loads(r.read())
    return result["choices"][0]["message"]["content"].strip()


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()

    if not text or user_id in busy:
        return

    if not authorized(user_id):
        await update.message.reply_text("NEXO access is not authorized for this Telegram account.")
        return

    gate = inspect_input(text)
    if not gate.get("allow"):
        await update.message.reply_text("I can't process that request.")
        return

    security = inspect_security(text)
    if not security.get("safe"):
        await update.message.reply_text("I can't process that request because it contains restricted information or an unsafe action.")
        return

    busy.add(user_id)
    try:
        session_id = get_or_create_session(user_id)

        fast = fast_tool(text)
        if fast is not None:
            message, verified = fast
            if verified:
                await update.message.reply_text(message)
            else:
                await update.message.reply_text(message + " I can confirm the command was dispatched, but I cannot independently verify the resulting app state.")
            save_turn(session_id, user_id, "user", text)
            save_turn(session_id, user_id, "assistant", message)
            return

        await update.message.chat.send_action("typing")

        turns = recent_turns(session_id, limit=8)
        messages = [{"role": "system", "content": SYSTEM}]
        messages.extend({"role": role, "content": content} for role, content in turns)
        messages.append({"role": "user", "content": text})

        answer = await asyncio.to_thread(ask_llama, messages)
        if not answer:
            answer = "I couldn't generate a response."

        save_turn(session_id, user_id, "user", text)
        save_turn(session_id, user_id, "assistant", answer)
        await update.message.reply_text(answer)

    except Exception as e:
        print("NEXO ERROR:", repr(e))
        await update.message.reply_text("Sorry, I couldn't complete that request right now.")
    finally:
        busy.discard(user_id)


app = Application.builder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

print("🤖 NEXO Telegram + Tools + Llama is running...")
app.run_polling(drop_pending_updates=True)
