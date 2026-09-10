"""Optional local Whisper.cpp STT and TTS integration hooks."""
from __future__ import annotations

import os
import subprocess


def transcribe(audio_path: str) -> dict:
    binary = os.getenv("WHISPER_CPP_BIN", "whisper-cli")
    model = os.getenv("WHISPER_CPP_MODEL", "").strip()
    if not model:
        return {"ok": False, "configured": False, "error": "WHISPER_CPP_MODEL is not configured"}
    try:
        p = subprocess.run([binary, "-m", model, "-f", audio_path, "-nt"], capture_output=True, text=True, timeout=120, check=False)
        return {"ok": p.returncode == 0, "text": p.stdout[-12000:], "error": p.stderr[-1000:] if p.returncode else ""}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def synthesize(text: str) -> dict:
    command = os.getenv("NEXO_TTS_COMMAND", "").strip()
    if not command:
        return {"ok": False, "configured": False, "error": "NEXO_TTS_COMMAND is not configured"}
    return {"ok": False, "configured": True, "error": "TTS hook is configured; deployment must provide the local command"}
