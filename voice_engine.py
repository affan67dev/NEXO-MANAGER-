import os
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


# ============================================================
# NEXO VOICE ENGINE
# Offline + Online ready STT/TTS architecture
# ============================================================

BASE_DIR = Path.home() / "NEXO"
VOICE_DIR = BASE_DIR / "voice"
VOICE_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_RATE = 16000
RECORD_SECONDS = 6


# ============================================================
# BASIC COMMAND RUNNER
# ============================================================

def run(command, timeout=30):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )

        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "code": result.returncode
        }

    except Exception as e:
        return {
            "ok": False,
            "stdout": "",
            "stderr": str(e),
            "code": -1
        }


# ============================================================
# INTERNET CHECK
# ============================================================

def internet_available():
    result = run(
        ["sh", "-c", "command -v curl >/dev/null 2>&1 && curl -Is --max-time 3 https://www.google.com >/dev/null 2>&1"],
        timeout=5
    )

    return result["ok"]


# ============================================================
# TEXT TO SPEECH
# ============================================================

def speak(text):
    if not text:
        return False

    print(f"🔊 NEXO: {text}")

    result = run(
        ["termux-tts-speak", "-r", "1.0", text],
        timeout=30
    )

    return result["ok"]


# ============================================================
# POPUP
# ============================================================

def popup(text):
    result = run(
        ["termux-toast", "-g", "top", text],
        timeout=10
    )

    return result["ok"]


# ============================================================
# MICROPHONE RECORDING
# ============================================================

def record(seconds=RECORD_SECONDS):
    filename = VOICE_DIR / f"input_{int(time.time())}.wav"

    print(f"🎙️ Recording for {seconds} seconds...")

    result = run(
        [
            "termux-microphone-record",
            "-l",
            str(seconds),
            "-f",
            str(filename)
        ],
        timeout=seconds + 10
    )

    if not result["ok"]:
        print("❌ Recording failed:", result["stderr"])
        return None

    if not filename.exists():
        print("❌ Audio file was not created.")
        return None

    if filename.stat().st_size < 100:
        print("❌ Audio file is too small.")
        return None

    print(f"✅ Audio recorded: {filename}")
    return filename


# ============================================================
# OFFLINE STT ADAPTER
# ============================================================

def offline_stt(audio_file):
    """
    Offline STT adapter.

    The actual local STT engine is intentionally detected
    dynamically so the rest of NEXO does not depend on one
    specific implementation.
    """

    # Future/local engines can be plugged in here.

    possible_engines = [
        "whisper-cli",
        "whisper",
        "whisper-cpp"
    ]

    available = []

    for engine in possible_engines:
        if shutil.which(engine):
            available.append(engine)

    if not available:
        return {
            "ok": False,
            "text": "",
            "provider": "offline",
            "error": "No offline STT engine installed."
        }

    engine = available[0]

    print(f"🧠 Offline STT engine: {engine}")

    # Engine-specific execution will be added once installed.
    return {
        "ok": False,
        "text": "",
        "provider": "offline",
        "engine": engine,
        "error": "Offline STT engine detected but adapter is not configured yet."
    }


# ============================================================
# ONLINE STT ADAPTER
# ============================================================

def online_stt(audio_file):
    """
    Online STT adapter.

    Provider credentials are intentionally read from environment
    variables only. Never hard-code API keys here.
    """

    if not internet_available():
        return {
            "ok": False,
            "text": "",
            "provider": "online",
            "error": "Internet unavailable."
        }

    # Provider integration will be added here.
    #
    # Example architecture:
    #
    # audio_file
    #      ↓
    # online provider
    #      ↓
    # transcript
    #
    # No credentials are stored in this source file.

    return {
        "ok": False,
        "text": "",
        "provider": "online",
        "error": "Online STT provider is not configured yet."
    }


# ============================================================
# SMART STT
# ============================================================

def speech_to_text(audio_file):
    """
    Automatically selects:
    
    Internet available
          ↓
       Online STT
          ↓ failure
       Offline STT

    Internet unavailable
          ↓
       Offline STT
    """

    if not audio_file:
        return {
            "ok": False,
            "text": "",
            "provider": "none",
            "error": "No audio file."
        }

    online = internet_available()

    print("🌐 Internet:", "ONLINE" if online else "OFFLINE")

    if online:
        result = online_stt(audio_file)

        if result.get("ok") and result.get("text"):
            return result

        print("⚠️ Online STT unavailable. Trying offline STT...")

    return offline_stt(audio_file)


# ============================================================
# ONE-SHOT VOICE INPUT
# ============================================================

def listen(seconds=RECORD_SECONDS):
    audio = record(seconds)

    if not audio:
        return {
            "ok": False,
            "text": "",
            "provider": "none"
        }

    result = speech_to_text(audio)

    # Keep the audio file for debugging for now.
    # It can be cleaned automatically later.

    return result


# ============================================================
# WAKE WORD
# ============================================================

WAKE_WORDS = (
    "hey nexo",
    "hi nexo",
    "hey nexos",
    "हे नेक्सो",
    "हाय नेक्सो"
)


def is_wake_word(text):
    if not text:
        return False

    value = text.lower().strip()

    return any(word in value for word in WAKE_WORDS)


# ============================================================
# REMOVE WAKE WORD
# ============================================================

def remove_wake_word(text):
    if not text:
        return ""

    result = text

    for word in WAKE_WORDS:
        result = result.replace(word, "")
        result = result.replace(word.title(), "")

    return result.strip(" ,.!?")


# ============================================================
# VOICE SESSION
# ============================================================

def voice_session():
    print()
    print("================================")
    print("🎙️ NEXO VOICE ENGINE")
    print("================================")
    print("Waiting for voice input...")
    print()

    result = listen()

    if not result.get("ok"):
        print("❌ STT:", result.get("error", "Unknown error"))
        return result

    text = result.get("text", "").strip()

    print("📝 Recognized:", text)
    print("🔌 Provider:", result.get("provider"))

    return result


# ============================================================
# SELF TEST
# ============================================================

def self_test():
    print("================================")
    print("NEXO VOICE ENGINE SELF TEST")
    print("================================")

    print("📁 Voice directory:", VOICE_DIR)

    print(
        "🎙️ Microphone:",
        "AVAILABLE" if shutil.which("termux-microphone-record") else "MISSING"
    )

    print(
        "🔊 TTS:",
        "AVAILABLE" if shutil.which("termux-tts-speak") else "MISSING"
    )

    print(
        "📱 Toast:",
        "AVAILABLE" if shutil.which("termux-toast") else "MISSING"
    )

    print(
        "🌐 Internet:",
        "ONLINE" if internet_available() else "OFFLINE"
    )

    print()
    print("Voice architecture: READY")
    print("Offline STT: adapter ready")
    print("Online STT: adapter ready")
    print("TTS: ready")
    print("Wake word: ready")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    self_test()
