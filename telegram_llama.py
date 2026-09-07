import os, json, urllib.request, asyncio, subprocess
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
import app_router

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
LLAMA_URL = "http://127.0.0.1:8080/v1/chat/completions"

SYSTEM_FILE = os.path.expanduser("~/NEXO/system_prompt.txt")
SYSTEM = open(SYSTEM_FILE, encoding="utf-8").read() if os.path.exists(SYSTEM_FILE) else "You are NEXO, a safe application operations assistant."

busy = set()
history = {}
MAX_HISTORY = 8


def fast_tool(text):
    t = text.lower().strip()

    # App open/search
    try:
        result = app_router.execute(text)
        if isinstance(result, dict) and result.get("ok"):
            action = result.get("command", {}).get("action")
            if action in ("open", "search"):
                return result.get("message", "Action completed.")
    except Exception:
        pass

    # Wi-Fi
    if any(x in t for x in ["wifi on", "wi-fi on", "wifi चालू", "वाईफाई चालू"]):
        p = subprocess.run(["termux-wifi-enable", "true"], capture_output=True, text=True)
        return "Wi-Fi enabled." if p.returncode == 0 else "Wi-Fi action failed."

    if any(x in t for x in ["wifi off", "wi-fi off", "wifi बंद", "वाईफाई बंद"]):
        p = subprocess.run(["termux-wifi-enable", "false"], capture_output=True, text=True)
        return "Wi-Fi disabled." if p.returncode == 0 else "Wi-Fi action failed."

    # Flashlight
    if any(x in t for x in ["flashlight on", "torch on", "flash on", "flashlight चालू", "torch चालू"]):
        p = subprocess.run(["termux-torch", "on"], capture_output=True, text=True)
        return "Flashlight enabled." if p.returncode == 0 else "Flashlight action failed."

    if any(x in t for x in ["flashlight off", "torch off", "flash off", "flashlight बंद", "torch बंद"]):
        p = subprocess.run(["termux-torch", "off"], capture_output=True, text=True)
        return "Flashlight disabled." if p.returncode == 0 else "Flashlight action failed."

    # Battery
    if any(x in t for x in ["battery status", "battery level", "battery कितनी", "बैटरी"]):
        p = subprocess.run(["termux-battery-status"], capture_output=True, text=True)
        if p.returncode == 0:
            try:
                b = json.loads(p.stdout)
                return f"Battery: {b.get('percentage', '?')}% | Status: {b.get('status', '?')} | Temperature: {b.get('temperature', '?')}°C"
            except Exception:
                return p.stdout.strip() or "Battery status unavailable."
        return "Battery status failed."

    return None


def ask_llama(messages):
    data = json.dumps({
        "messages": messages,
        "temperature": 0.15,
        "max_tokens": 256,
        "stream": False
    }).encode()

    req = urllib.request.Request(
        LLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req, timeout=180) as r:
        result = json.loads(r.read())

    return result["choices"][0]["message"]["content"].strip()


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not text or user_id in busy:
        return

    busy.add(user_id)

    try:
        result = fast_tool(text)

        if result is not None:
            await update.message.reply_text(result)
            return

        await update.message.chat.send_action("typing")

        messages = [{"role": "system", "content": SYSTEM}]
        messages += history.get(user_id, [])
        messages.append({"role": "user", "content": text})

        answer = await asyncio.to_thread(ask_llama, messages)

        if not answer:
            answer = "I couldn't generate a response."

        history.setdefault(user_id, []).extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": answer}
        ])
        history[user_id] = history[user_id][-MAX_HISTORY:]

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
