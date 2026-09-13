"""NEXO Voice Assistant: wake word -> STT -> NEXO Manager -> tools -> TTS.

The module is intentionally dependency-light.  Optional integrations are detected
at runtime so the existing NEXO manager remains the single routing brain.

Supported runtime targets:
- Android/Termux: microphone, Termux TTS, allowed app launch/search, split-screen intent
- Windows/macOS: adapter surface with explicit unsupported responses until a native
  controller is installed.  No fake success is returned.

STT priority:
1. faster-whisper Python package when installed and NEXO_WHISPER_MODEL is configured
2. whisper.cpp/whisper-cli when installed and NEXO_WHISPER_MODEL is configured

Wake word:
- optional openWakeWord model when installed/configured
- deterministic transcript gate fallback ("hey nexo"/Hindi variants)

Security:
- only allowlisted tools are executable
- destructive/sensitive actions require explicit confirmation
- tool failures are never reported as success
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from core.router import create_task

BASE_DIR = Path.home() / "NEXO"
VOICE_DIR = BASE_DIR / "voice"
VOICE_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_RATE = int(os.getenv("NEXO_VOICE_SAMPLE_RATE", "16000"))
RECORD_SECONDS = int(os.getenv("NEXO_VOICE_RECORD_SECONDS", "6"))

WAKE_WORDS = (
    "hey nexo", "hi nexo", "hey nexos", "हे नेक्सो", "हाय नेक्सो"
)


@dataclass
class VoiceResult:
    ok: bool
    text: str = ""
    response: str = ""
    stage: str = ""
    provider: str = ""
    verified: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "text": self.text, "response": self.response,
            "stage": self.stage, "provider": self.provider,
            "verified": self.verified, "details": self.details,
        }


def _run(command: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        p = subprocess.run(command, capture_output=True, text=True,
                           timeout=timeout, check=False)
        return {"ok": p.returncode == 0, "stdout": p.stdout.strip(),
                "stderr": p.stderr.strip(), "code": p.returncode}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc), "code": -1}


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def internet_available() -> bool:
    if not _command_exists("curl"):
        return False
    return _run(["curl", "-Is", "--max-time", "3", "https://www.google.com"], 5)["ok"]


# ------------------------------- TTS ---------------------------------

def speak(text: str) -> bool:
    """Speak text and return the real subprocess result; never fake success."""
    text = (text or "").strip()
    if not text:
        return False
    if _command_exists("termux-tts-speak"):
        return _run(["termux-tts-speak", "-r", "1.0", text], 30)["ok"]
    if platform.system() == "Windows" and _command_exists("powershell"):
        script = "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($args[0])"
        return _run(["powershell", "-NoProfile", "-Command", script, text], 30)["ok"]
    if platform.system() == "Darwin" and _command_exists("say"):
        return _run(["say", text], 30)["ok"]
    return False


# ------------------------------ Microphone ----------------------------

def record(seconds: int = RECORD_SECONDS) -> Optional[Path]:
    """Record microphone input on Termux.  Desktop capture is deliberately explicit."""
    seconds = max(1, min(int(seconds), 60))
    filename = VOICE_DIR / f"input_{int(time.time() * 1000)}.wav"
    if not _command_exists("termux-microphone-record"):
        return None
    result = _run(["termux-microphone-record", "-l", str(seconds), "-f", str(filename)], seconds + 10)
    if not result["ok"] or not filename.exists() or filename.stat().st_size < 100:
        return None
    return filename


# -------------------------------- STT ---------------------------------

def _faster_whisper_stt(audio_file: Path) -> dict[str, Any]:
    model_name = os.getenv("NEXO_WHISPER_MODEL", "")
    if not model_name or importlib.util.find_spec("faster_whisper") is None:
        return {"ok": False, "error": "faster-whisper is not configured"}
    try:
        from faster_whisper import WhisperModel
        device = os.getenv("NEXO_WHISPER_DEVICE", "cpu")
        compute = os.getenv("NEXO_WHISPER_COMPUTE", "int8")
        model = WhisperModel(model_name, device=device, compute_type=compute)
        segments, info = model.transcribe(str(audio_file), vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"ok": bool(text), "text": text, "provider": "faster-whisper",
                "language": getattr(info, "language", None)}
    except Exception as exc:
        return {"ok": False, "error": f"faster-whisper: {exc}"}


def _whisper_cpp_stt(audio_file: Path) -> dict[str, Any]:
    model = os.getenv("NEXO_WHISPER_MODEL", "")
    if not model:
        return {"ok": False, "error": "NEXO_WHISPER_MODEL is not configured"}
    binary = next((x for x in ("whisper-cli", "whisper-cpp", "whisper") if _command_exists(x)), None)
    if not binary:
        return {"ok": False, "error": "whisper.cpp CLI is not installed"}
    result = _run([binary, "-m", model, "-f", str(audio_file), "-nt", "-np"], 120)
    if not result["ok"]:
        return {"ok": False, "error": result["stderr"] or "whisper.cpp failed"}
    text = re.sub(r"\\s+", " ", result["stdout"]).strip()
    return {"ok": bool(text), "text": text, "provider": "whisper.cpp"}


def speech_to_text(audio_file: Path | str) -> dict[str, Any]:
    path = Path(audio_file)
    if not path.exists():
        return {"ok": False, "text": "", "provider": "none", "error": "audio file missing"}
    for adapter in (_faster_whisper_stt, _whisper_cpp_stt):
        result = adapter(path)
        if result.get("ok") and result.get("text"):
            return result
    return {"ok": False, "text": "", "provider": "none",
            "error": "No configured STT engine succeeded"}


# ---------------------------- Wake word --------------------------------

def normalize(text: str) -> str:
    return re.sub(r"\\s+", " ", (text or "").strip().lower())


def is_wake_word(text: str) -> bool:
    value = normalize(text)
    return any(word in value for word in WAKE_WORDS)


def remove_wake_word(text: str) -> str:
    value = text or ""
    for word in WAKE_WORDS:
        value = re.sub(re.escape(word), "", value, flags=re.I)
    return value.strip(" ,.!?;:")


def detect_wake_word_from_audio(audio_file: Path | str) -> bool:
    """Use openWakeWord if available; otherwise use the STT transcript gate.

    A real openWakeWord model must be supplied through NEXO_WAKE_MODEL.  This avoids
    silently pretending that a generic model is the exact 'Hey Nexo' wake word.
    """
    model_path = os.getenv("NEXO_WAKE_MODEL", "")
    if model_path and importlib.util.find_spec("openwakeword") is not None:
        try:
            from openwakeword.model import Model
            import wave
            import numpy as np
            with wave.open(str(audio_file), "rb") as wav:
                frames = wav.readframes(wav.getnframes())
                rate = wav.getframerate()
            if rate != 16000:
                return False
            model = Model(wakeword_models=[model_path], inference_framework="onnx")
            audio = np.frombuffer(frames, dtype=np.int16)
            scores = model.predict(audio)
            return bool(scores and max(float(v) for v in scores.values()) >= float(os.getenv("NEXO_WAKE_THRESHOLD", "0.5")))
        except Exception:
            return False
    transcript = speech_to_text(Path(audio_file))
    return bool(transcript.get("ok") and is_wake_word(transcript.get("text", "")))


# ------------------------- Device/tool adapters -----------------------

SAFE_APPS = {"youtube", "instagram", "telegram", "chrome", "google"}
SENSITIVE_TERMS = ("delete", "wipe", "factory reset", "shutdown", "format", "password", "credential", "payment")


def _android_app_action(command: str) -> dict[str, Any]:
    """Reuse the existing app router rather than creating a second NEXO brain."""
    import app_router
    parsed = app_router.parse_command(command)
    app = parsed.get("app")
    if app not in SAFE_APPS:
        return {"ok": False, "verified": False, "error": "app_not_allowlisted", "command": parsed}
    result = app_router.execute(command)
    result["verified"] = bool(result.get("ok"))
    return result


def _android_split_screen(command: str) -> dict[str, Any]:
    """Best-effort Android split-screen adapter; reports unsupported instead of lying."""
    if not _command_exists("am"):
        return {"ok": False, "verified": False, "error": "Android am command unavailable"}
    # Split-screen layout is OS/version/launcher specific.  We only expose the adapter
    # and require an explicit Android implementation command from the deployment.
    intent = os.getenv("NEXO_ANDROID_SPLIT_COMMAND", "")
    if not intent:
        return {"ok": False, "verified": False, "error": "split-screen adapter not configured for this Android build"}
    result = _run(["sh", "-c", intent], 20)
    return {"ok": result["ok"], "verified": result["ok"], "stdout": result["stdout"], "error": result["stderr"]}


def execute_tool(text: str, confirmation: bool = False) -> dict[str, Any]:
    """Execute only supported, low-risk device actions through existing adapters."""
    normalized = normalize(text)
    if any(term in normalized for term in SENSITIVE_TERMS) and not confirmation:
        return {"ok": False, "verified": False, "requires_confirmation": True,
                "message": "This action requires explicit confirmation."}

    if "side" in normalized and ("whatsapp" in normalized or "split" in normalized):
        return _android_split_screen(text)

    if platform.system() in {"Linux", "Android"}:
        return _android_app_action(text)
    return {"ok": False, "verified": False,
            "error": f"No native device adapter enabled for {platform.system()}"}


# ----------------------------- Pipeline -------------------------------

class NexoVoiceAssistant:
    """End-to-end voice controller using the existing NEXO Manager/Router."""

    def __init__(self, stt: Callable[[Path | str], dict[str, Any]] = speech_to_text,
                 tts: Callable[[str], bool] = speak,
                 recorder: Callable[[int], Optional[Path]] = record,
                 tool_executor: Callable[[str, bool], dict[str, Any]] = execute_tool) -> None:
        self.stt = stt
        self.tts = tts
        self.recorder = recorder
        self.tool_executor = tool_executor

    def process_text(self, text: str, confirmation: bool = False) -> VoiceResult:
        text = (text or "").strip()
        if not text:
            return VoiceResult(False, stage="input")

        if is_wake_word(text):
            command = remove_wake_word(text)
            if not command:
                response = "Yes, how can I help you?"
                spoken = self.tts(response)
                return VoiceResult(True, text=text, response=response, stage="wake", provider="text",
                                   verified=spoken, details={"tts_verified": spoken})
            text = command

        # This is the existing NEXO brain.  We do not create another router.
        task = create_task(text)
        tool_result = self.tool_executor(text, confirmation)
        if tool_result.get("requires_confirmation"):
            response = "I need your confirmation before I do that."
        elif tool_result.get("ok"):
            response = str(tool_result.get("message", "Done."))
        elif task.agent == "manager":
            response = "I understood the request, but I don't have an approved tool for that action yet."
        else:
            response = f"NEXO routed this request to {task.agent}, but no voice execution adapter is enabled for it yet."

        spoken = self.tts(response)
        return VoiceResult(bool(tool_result.get("ok")) or tool_result.get("requires_confirmation", False),
                           text=text, response=response, stage="execute", provider="nexo-manager",
                           verified=bool(tool_result.get("verified")) and spoken,
                           details={"agent": task.agent, "intent": task.intent,
                                    "tool": tool_result, "tts_verified": spoken})

    def listen_once(self, seconds: int = RECORD_SECONDS) -> VoiceResult:
        audio = self.recorder(seconds)
        if not audio:
            return VoiceResult(False, stage="record", details={"error": "microphone recording failed"})
        stt = self.stt(audio)
        if not stt.get("ok"):
            return VoiceResult(False, stage="stt", provider=stt.get("provider", "none"),
                               details=stt)
        return self.process_text(stt.get("text", ""))

    def run_forever(self, seconds: int = 3) -> None:
        """Background wake loop.  In transcript-fallback mode this consumes STT audio.
        For low-power true wake detection, configure NEXO_WAKE_MODEL/openWakeWord.
        """
        while True:
            audio = self.recorder(seconds)
            if not audio:
                time.sleep(1)
                continue
            if not detect_wake_word_from_audio(audio):
                continue
            stt = self.stt(audio)
            if not stt.get("ok"):
                continue
            self.process_text(stt.get("text", ""))


def self_test() -> dict[str, Any]:
    return {
        "microphone": _command_exists("termux-microphone-record"),
        "tts": _command_exists("termux-tts-speak") or _command_exists("say") or _command_exists("powershell"),
        "stt_faster_whisper_installed": importlib.util.find_spec("faster_whisper") is not None,
        "stt_whisper_cli_installed": any(_command_exists(x) for x in ("whisper-cli", "whisper-cpp", "whisper")),
        "wake_model_configured": bool(os.getenv("NEXO_WAKE_MODEL")),
        "nexo_router": True,
        "android_split_configured": bool(os.getenv("NEXO_ANDROID_SPLIT_COMMAND")),
    }


# Backward-compatible aliases used by the original script.
def listen(seconds: int = RECORD_SECONDS) -> dict[str, Any]:
    result = NexoVoiceAssistant().listen_once(seconds)
    return result.as_dict()


def voice_session() -> dict[str, Any]:
    result = NexoVoiceAssistant().listen_once()
    return result.as_dict()


if __name__ == "__main__":
    print(json.dumps(self_test(), indent=2))
