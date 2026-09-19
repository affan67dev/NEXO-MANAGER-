"""ALEX voice runtime: microphone -> wake -> state machine -> existing manager/planner/tools -> TTS.

Technical NEXO module names remain compatible by design; ALEX is the user-facing voice identity.
"""
from __future__ import annotations
import importlib.util, json, logging, os, platform, re, shutil, subprocess, time, uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional
from android_capabilities import toast_state
from services.llm_provider import LLMConfig
from core.alex_agent_loop import AlexAgentLoop, Decision

logger = logging.getLogger("nexo.alex.voice")

from agents.executive_planner import ExecutivePlanner
from core.router import create_task
from core.task_orchestrator import TaskOrchestrator, TaskSpec, specs_from_plan
from tool_registry import execute as execute_registered_tool, schemas
import nexo_tools  # noqa: F401

BASE_DIR = Path.home() / "NEXO"
VOICE_DIR = BASE_DIR / "voice"
VOICE_DIR.mkdir(parents=True, exist_ok=True)
RECORD_SECONDS = int(os.getenv("NEXO_VOICE_RECORD_SECONDS", "6"))
ACTIVE_TIMEOUT_SECONDS = 30.0
VOICE_IDLE_POLLING = os.getenv("NEXO_VOICE_IDLE_POLLING", "false").strip().lower() == "true"
WAKE_WORDS = (
    "hey alex", "hi alex", "hey alexa",
    "हे एलेक्स", "हाय एलेक्स", "हे एलेक्सा", "हाय एलेक्सा",
)
SENSITIVE_TERMS = ("delete", "wipe", "factory reset", "shutdown", "format", "password",
                   "credential", "payment", "send message", "send whatsapp")

class VoiceState(str, Enum):
    IDLE = "IDLE"
    WAKE_DETECTED = "WAKE_DETECTED"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    UNDERSTANDING = "UNDERSTANDING"
    ANALYSING = "ANALYSING"
    DECIDING = "DECIDING"
    PLANNING = "PLANNING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"

@dataclass
class VoiceResult:
    ok: bool
    text: str = ""
    response: str = ""
    stage: str = ""
    provider: str = ""
    verified: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    state: str = VoiceState.IDLE.value
    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

def _run(command: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        p = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return {"ok": p.returncode == 0, "stdout": p.stdout.strip(), "stderr": p.stderr.strip(), "code": p.returncode}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc), "code": -1}

def _exists(name: str) -> bool:
    return shutil.which(name) is not None

def _load_runtime_env() -> None:
    """Load ~/.nexo.env without overwriting explicit process environment variables."""
    env_file = Path.home() / ".nexo.env"
    if not env_file.is_file():
        return
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('\"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


def speak(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    if _exists("termux-tts-speak"):
        return _run(["termux-tts-speak", "-r", "1.0", text], 30)["ok"]
    if platform.system() == "Windows" and _exists("powershell"):
        return _run(["powershell", "-NoProfile", "-Command",
                     "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($args[0])",
                     text], 30)["ok"]
    if platform.system() == "Darwin" and _exists("say"):
        return _run(["say", text], 30)["ok"]
    return False

def record(seconds: int = RECORD_SECONDS) -> Optional[Path]:
    seconds = max(1, min(int(seconds), 60))
    filename = VOICE_DIR / f"input_{int(time.time() * 1000)}.wav"
    if not _exists("termux-microphone-record"):
        return None
    result = _run(["termux-microphone-record", "-l", str(seconds), "-f", str(filename)], seconds + 10)
    return filename if result["ok"] and filename.exists() and filename.stat().st_size >= 100 else None

def termux_speech_to_text() -> dict[str, Any]:
    if not _exists("termux-speech-to-text"):
        return {"ok": False, "provider": "termux-speech-to-text", "error": "Termux:API speech command unavailable"}
    result = _run(["termux-speech-to-text"], 90)
    if not result["ok"] or not result["stdout"]:
        return {"ok": False, "provider": "termux-speech-to-text",
                "error": result["stderr"] or "speech recognition returned no text"}
    return {"ok": True, "text": result["stdout"], "provider": "termux-speech-to-text"}

def _faster_whisper(audio: Path) -> dict[str, Any]:
    model = os.getenv("NEXO_WHISPER_MODEL", "").strip()
    if not model or importlib.util.find_spec("faster_whisper") is None:
        return {"ok": False, "error": "faster-whisper/model not configured"}
    try:
        from faster_whisper import WhisperModel
        engine = WhisperModel(model, device=os.getenv("NEXO_WHISPER_DEVICE", "cpu"),
                              compute_type=os.getenv("NEXO_WHISPER_COMPUTE", "int8"))
        segments, info = engine.transcribe(str(audio), vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"ok": bool(text), "text": text, "provider": "faster-whisper",
                "language": getattr(info, "language", None)}
    except Exception as exc:
        return {"ok": False, "error": f"faster-whisper: {exc}"}

def _whisper_cpp(audio: Path) -> dict[str, Any]:
    model = os.getenv("NEXO_WHISPER_MODEL", "").strip()
    binary = next((x for x in ("whisper-cli", "whisper-cpp", "whisper") if _exists(x)), None)
    if not model or not binary:
        return {"ok": False, "error": "whisper.cpp/model not configured"}
    result = _run([binary, "-m", model, "-f", str(audio), "-nt", "-np"], 120)
    if not result["ok"]:
        return {"ok": False, "error": result["stderr"] or "whisper.cpp failed"}
    return {"ok": bool(result["stdout"]), "text": re.sub(r"\s+", " ", result["stdout"]).strip(),
            "provider": "whisper.cpp"}

def speech_to_text(audio_file: Path | str | None = None) -> dict[str, Any]:
    if audio_file is None:
        return termux_speech_to_text()
    path = Path(audio_file)
    if not path.exists():
        return {"ok": False, "provider": "none", "error": "audio file missing"}
    for adapter in (_faster_whisper, _whisper_cpp):
        result = adapter(path)
        if result.get("ok"):
            return result
    return {"ok": False, "provider": "none", "error": "No configured STT engine succeeded"}

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())

def is_wake_word(text: str) -> bool:
    value = normalize(text)
    patterns = (
        r"^hey[\s,]+alex(?:\s|[,.!?;:]|$)",
        r"^hi[\s,]+alex(?:\s|[,.!?;:]|$)",
        r"^hey[\s,]+aleks(?:\s|[,.!?;:]|$)",
        r"^हे[\s,]+एलेक्स(?:\s|[,.!?;:]|$)",
        r"^हाय[\s,]+एलेक्स(?:\s|[,.!?;:]|$)",
    )
    return any(re.match(p, value, flags=re.I) for p in patterns)

def remove_wake_word(text: str) -> str:
    value = (text or "").strip()
    patterns = (
        r"^hey[\s,]+alex(?:\s|[,.!?;:]*)",
        r"^hi[\s,]+alex(?:\s|[,.!?;:]*)",
        r"^hey[\s,]+aleks(?:\s|[,.!?;:]*)",
        r"^हे[\s,]+एलेक्स(?:\s|[,.!?;:]*)",
        r"^हाय[\s,]+एलेक्स(?:\s|[,.!?;:]*)",
    )
    for pattern in patterns:
        value = re.sub(pattern, "", value, flags=re.I)
    return value.strip(" ,.!?;:")

def _execute_voice_tool(name: str, args: dict[str, Any], *, owner: bool = True,
                        user_id: int | str | None = None, confirmation: bool = False) -> dict[str, Any]:
    serialized = json.dumps(args, ensure_ascii=False).lower()
    if any(term in name.lower() or term in serialized for term in SENSITIVE_TERMS):
        if not owner:
            return {"ok": False, "verified": False, "requires_confirmation": True, "error": "owner_authorization_required"}
        if not confirmation:
            return {"ok": False, "verified": False, "requires_confirmation": True, "error": "explicit_confirmation_required"}
    result = execute_registered_tool(name, args, owner=owner, user_id=user_id)
    result.setdefault("verified", False)
    return result

def _fallback_plan(text: str) -> list[dict[str, Any]]:
    parts = [p.strip(" ,.;") for p in re.split(r"\s+(?:and then|then|after that|and)\s+|\s*;\s*", text, flags=re.I) if p.strip()]
    if not parts:
        parts = [text.strip()]
    result, previous = [], None
    for part in parts[:20]:
        tid = f"task-{uuid.uuid4().hex[:10]}"
        deps = [previous] if previous else []
        result.append({"task_id": tid, "objective": part, "dependencies": deps, "priority": "normal",
                       "kind": "dependent" if deps else "sequential",
                       "expected_result": f"Successful completion of: {part}", "max_retries": 2,
                       "timeout_seconds": 90, "parameters": {}})
        previous = tid
    return result

def execute_via_nexo(text: str, *, owner: bool = True, user_id: int | str | None = None,
                     confirmation: bool = False, planner: ExecutivePlanner | None = None,
                     phase_callback: Callable[[VoiceState], None] | None = None) -> dict[str, Any]:
    _load_runtime_env()
    if phase_callback: phase_callback(VoiceState.UNDERSTANDING)
    preliminary = AlexAgentLoop().inspect(text, user_id=user_id, owner_id=None if owner else -1)
    if preliminary.decision is Decision.CLARIFICATION:
        return {"ok": False, "verified": False, "response": preliminary.reason, "stage": "analysis", "decision": preliminary.decision.value}
    if preliminary.decision is Decision.CONFIRMATION and not confirmation:
        if phase_callback: phase_callback(VoiceState.AWAITING_CONFIRMATION)
        return {"ok": False, "verified": False, "requires_confirmation": True, "response": "I need your explicit confirmation before I do that.", "stage": "confirmation", "decision": preliminary.decision.value}
    if phase_callback: phase_callback(VoiceState.ANALYSING)
    manager_task = create_task(text)
    if planner is None:
        try:
            LLMConfig.from_env()
            planner = ExecutivePlanner()
        except RuntimeError as exc:
            return {"ok": False, "verified": False,
                    "response": "ALEX reasoning is not configured. Set LLM_PROVIDER, LLM_API_KEY and LLM_MODEL in ~/.nexo.env.",
                    "error": str(exc), "stage": "llm_configuration"}
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    if phase_callback: phase_callback(VoiceState.DECIDING)
    try:
        if phase_callback: phase_callback(VoiceState.PLANNING)
        plan = planner.plan_tasks(text, context=[{"intent": manager_task.intent, "agent": manager_task.agent}])
    except Exception:
        plan = []
    if not plan:
        plan = _fallback_plan(text)
    tasks = specs_from_plan(plan) or [TaskSpec(objective=text)]
    if len(tasks) > 1:
        ids = {t.task_id for t in tasks}
        for t in tasks:
            t.dependencies = [d for d in t.dependencies if d in ids]
    orchestrator = TaskOrchestrator()
    observed = []

    def execute_task(task: TaskSpec) -> dict[str, Any]:
        if phase_callback: phase_callback(VoiceState.EXECUTING)
        local = []
        def executor(name, args, **kw):
            result = _execute_voice_tool(name, args, owner=owner, user_id=user_id, confirmation=confirmation)
            local.append({"name": name, "args": args, "result": result})
            observed.append({"task_id": task.task_id, "name": name, "args": args, "result": result})
            return result
        messages = [{"role": "system", "content":
                     "You are ALEX's execution planner. Use the existing NEXO Manager orchestration. "
                     "Understand the objective, select only registered tools, and never claim success unless a tool returns verified=true."},
                    {"role": "user", "content": task.objective}]
        try:
            answer = planner.run(task.objective, messages, schemas(), executor, owner=owner, user_id=user_id, max_steps=6)
        except Exception as exc:
            return {"ok": False, "verified": False, "permanent": False,
                    "error": f"hosted_execution_failed:{type(exc).__name__}",
                    "response": "I couldn't execute that task because the reasoning service failed."}
        requires = any(x["result"].get("requires_confirmation") for x in local)
        if phase_callback: phase_callback(VoiceState.VERIFYING)
        if phase_callback: phase_callback(VoiceState.VERIFYING)
        verified = bool(local) and all(x["result"].get("verified") is True for x in local) and not requires
        return {"ok": verified, "verified": verified, "requires_confirmation": requires,
                "response": answer, "tools": local}

    try:
        results = orchestrator.run(request_id, tasks, execute_task, max_parallel=2)
    except Exception as exc:
        return {"ok": False, "verified": False, "response": "I couldn't safely complete the task plan.",
                "agent": manager_task.agent, "intent": manager_task.intent, "tools": observed,
                "tasks": [], "error": type(exc).__name__}
    requires = any(r.get("requires_confirmation") for r in results)
    all_verified = bool(results) and all(r.get("state") == "completed" and r.get("verified") for r in results) and not requires
    failed = [r for r in results if r.get("state") == "failed"]
    response = ("I need your explicit confirmation before I do that." if requires else
                ("Some tasks failed, but I preserved the remaining task state." if failed
                 else str(results[-1].get("response") or "Task completed.")))
    return {"ok": all_verified, "verified": all_verified, "response": response,
            "agent": manager_task.agent, "intent": manager_task.intent, "tools": observed,
            "tasks": results, "request_id": request_id, "requires_confirmation": requires}

class NexoVoiceAssistant:
    """Compatibility class: NexoVoiceAssistant remains importable; user-facing identity is ALEX."""
    def __init__(self, stt: Callable = speech_to_text, tts: Callable[[str], bool] = speak,
                 recorder: Callable[[int], Optional[Path]] = record, timeout_seconds: float = ACTIVE_TIMEOUT_SECONDS):
        self.stt, self.tts, self.recorder = stt, tts, recorder
        self.timeout_seconds = float(timeout_seconds)
        self.state = VoiceState.IDLE
        self.last_interaction = 0.0

    def _set_state(self, state: VoiceState) -> None:
        self.state = state
        if state is VoiceState.IDLE:
            return
        try:
            toast_state(state.value)
        except Exception:
            logger.debug("voice_ui_update_failed", exc_info=True)

    def activation_response(self) -> str:
        return "Yes, how can I help you?"

    def process_text(self, text: str, owner: bool = True, user_id: int | str | None = None,
                     confirmation: bool = False, planner: ExecutivePlanner | None = None) -> VoiceResult:
        text = (text or "").strip()
        if not text:
            return VoiceResult(False, stage="input", state=self.state.value)
        if is_wake_word(text):
            command = remove_wake_word(text)
            command_discarded = bool(command)
            self._set_state(VoiceState.WAKE_DETECTED)
            self.last_interaction = time.monotonic()
            self._set_state(VoiceState.SPEAKING)
            response = self.activation_response()
            spoken = self.tts(response)
            self._set_state(VoiceState.LISTENING if spoken else VoiceState.IDLE)
            return VoiceResult(True, response=response, stage="wake", provider="text",
                               verified=spoken, details={"tts_verified": spoken, "command_discarded": command_discarded},
                               state=self.state.value)
        self._set_state(VoiceState.PROCESSING)
        self.last_interaction = time.monotonic()
        outcome = execute_via_nexo(text, owner=owner, user_id=user_id, confirmation=confirmation, planner=planner, phase_callback=self._set_state)
        response = str(outcome.get("response") or "")
        self._set_state(VoiceState.SPEAKING)
        spoken = self.tts(response)
        self._set_state(VoiceState.LISTENING if spoken else VoiceState.IDLE)
        return VoiceResult(outcome.get("ok", False), text=text, response=response, stage="execute",
                           provider="nexo-manager", verified=bool(outcome.get("verified")) and spoken,
                           details=outcome | {"tts_verified": spoken}, state=self.state.value)

    def _listen_input(self) -> dict[str, Any]:
        stt = self.stt(None) if self.stt is speech_to_text else None
        if stt is None:
            audio = self.recorder(RECORD_SECONDS)
            if not audio:
                return {"ok": False, "provider": "microphone", "error": "microphone recording failed"}
            stt = self.stt(audio)
        return stt

    def listen_once(self, seconds: int = RECORD_SECONDS, owner: bool = True,
                    user_id: int | str | None = None, confirmation: bool = False) -> VoiceResult:
        stt = self.stt(None) if self.stt is speech_to_text else None
        if stt is None:
            audio = self.recorder(seconds)
            if not audio:
                return VoiceResult(False, stage="record", details={"error": "microphone recording failed"}, state=self.state.value)
            stt = self.stt(audio)
        if not stt.get("ok"):
            return VoiceResult(False, stage="stt", provider=stt.get("provider", "none"),
                               details=stt, state=self.state.value)
        result = self.process_text(stt.get("text", ""), owner=owner, user_id=user_id, confirmation=confirmation)
        result.details["stt"] = stt
        return result

    def active_timeout_expired(self, now: float | None = None) -> bool:
        if self.state not in {VoiceState.LISTENING, VoiceState.WAKE_DETECTED}:
            return False
        return (now if now is not None else time.monotonic()) - self.last_interaction >= self.timeout_seconds

    def timeout_check(self, now: float | None = None) -> bool:
        if self.active_timeout_expired(now):
            self._set_state(VoiceState.IDLE)
            self.last_interaction = 0.0
            return True
        return False

    def wake_once(self, owner: bool = True, user_id: int | str | None = None) -> VoiceResult:
        """Perform exactly one wake recognition attempt.

        Termux speech-to-text is one-shot, not a hotword engine. Keeping wake detection
        explicit prevents an IDLE daemon from repeatedly opening the microphone.
        """
        if self.state != VoiceState.IDLE:
            return VoiceResult(False, stage="wake", details={"error": "voice_session_already_active"}, state=self.state.value)
        stt = self._listen_input()
        if not stt.get("ok"):
            return VoiceResult(False, stage="wake_stt", provider=stt.get("provider", "none"), details=stt, state=self.state.value)
        text = str(stt.get("text") or "").strip()
        if not is_wake_word(text):
            return VoiceResult(False, text=text, stage="wake", provider=stt.get("provider", "unknown"),
                               details={"wake_detected": False, "stt": stt}, state=self.state.value)
        result = self.process_text(text, owner=owner, user_id=user_id)
        result.details["stt"] = stt
        return result

    def run_active_session(self, owner: bool = True, user_id: int | str | None = None) -> None:
        """Run only the post-wake conversation loop until 30s of inactivity."""
        if self.state == VoiceState.IDLE:
            return
        while self.state != VoiceState.IDLE:
            try:
                if self.timeout_check():
                    return
                self._set_state(VoiceState.LISTENING)
                stt = self._listen_input()
                if not stt.get("ok"):
                    self._set_state(VoiceState.IDLE)
                    return
                text = str(stt.get("text") or "").strip()
                if not text:
                    if self.timeout_check():
                        return
                    continue
                self.last_interaction = time.monotonic()
                self.process_text(text, owner=owner, user_id=user_id)
            except KeyboardInterrupt:
                self._set_state(VoiceState.IDLE)
                return
            except Exception:
                try:
                    from android_capabilities import show_voice_error
                    show_voice_error()
                except Exception:
                    logger.debug("voice_error_ui_failed", exc_info=True)
                self._set_state(VoiceState.IDLE)
                return

    def run_forever(self, owner: bool = True, user_id: int | str | None = None) -> None:
        """Keep runtime alive without pretending Termux STT is an always-on hotword engine."""
        while True:
            try:
                if self.state == VoiceState.IDLE:
                    if VOICE_IDLE_POLLING:
                        result = self.wake_once(owner=owner, user_id=user_id)
                        if result.ok and self.state != VoiceState.IDLE:
                            self.run_active_session(owner=owner, user_id=user_id)
                        time.sleep(max(5.0, float(os.getenv("NEXO_VOICE_IDLE_POLL_SECONDS", "10"))))
                    else:
                        time.sleep(1.0)
                    continue
                self.run_active_session(owner=owner, user_id=user_id)
            except KeyboardInterrupt:
                self._set_state(VoiceState.IDLE)
                break
            except Exception as exc:
                logger.exception("voice_runtime_error type=%s", type(exc).__name__)
                self._set_state(VoiceState.IDLE)
                time.sleep(1)

def self_test() -> dict[str, Any]:
    return {
        "termux_microphone_stt": _exists("termux-speech-to-text"),
        "termux_record": _exists("termux-microphone-record"),
        "tts": _exists("termux-tts-speak") or _exists("say") or _exists("powershell"),
        "faster_whisper_installed": importlib.util.find_spec("faster_whisper") is not None,
        "whisper_cli_installed": any(_exists(x) for x in ("whisper-cli", "whisper-cpp", "whisper")),
        "wake_model_configured": bool(os.getenv("NEXO_WAKE_MODEL")),
        "idle_microphone_polling": VOICE_IDLE_POLLING,
        "llm": "configured via LLM_PROVIDER",
        "registered_tools": len(schemas()),
        "state_machine": [s.value for s in VoiceState],
        "active_timeout_seconds": ACTIVE_TIMEOUT_SECONDS,
    }

def listen(seconds: int = RECORD_SECONDS) -> dict[str, Any]:
    return NexoVoiceAssistant().listen_once(seconds).as_dict()

def voice_session() -> dict[str, Any]:
    return NexoVoiceAssistant().listen_once().as_dict()

if __name__ == "__main__":
    print(json.dumps(self_test(), indent=2, ensure_ascii=False))
