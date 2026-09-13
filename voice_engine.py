"""NEXO voice runtime: microphone -> wake -> STT -> NEXO/LLaMA -> tools -> TTS."""
from __future__ import annotations
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from agents.executive_planner import ExecutivePlanner
from core.router import create_task
from tool_registry import execute as execute_registered_tool, schemas
import nexo_tools  # noqa: F401

BASE_DIR = Path.home() / "NEXO"
VOICE_DIR = BASE_DIR / "voice"
VOICE_DIR.mkdir(parents=True, exist_ok=True)
RECORD_SECONDS = int(os.getenv("NEXO_VOICE_RECORD_SECONDS", "6"))
LLAMA_URL = os.getenv("LLAMA_URL", "http://127.0.0.1:8080/v1/chat/completions").strip()
WAKE_WORDS = ("hey nexo", "hi nexo", "hey nexos", "हे नेक्सो", "हाय नेक्सो")
SENSITIVE_TERMS = ("delete", "wipe", "factory reset", "shutdown", "format", "password", "credential", "payment", "send message", "send whatsapp")

@dataclass
class VoiceResult:
    ok: bool
    text: str = ""
    response: str = ""
    stage: str = ""
    provider: str = ""
    verified: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    def as_dict(self) -> dict[str, Any]: return self.__dict__.copy()

def _run(command: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        p = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return {"ok": p.returncode == 0, "stdout": p.stdout.strip(), "stderr": p.stderr.strip(), "code": p.returncode}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc), "code": -1}

def _exists(name: str) -> bool: return shutil.which(name) is not None

def speak(text: str) -> bool:
    text = (text or "").strip()
    if not text: return False
    if _exists("termux-tts-speak"): return _run(["termux-tts-speak", "-r", "1.0", text], 30)["ok"]
    if platform.system() == "Windows" and _exists("powershell"):
        return _run(["powershell", "-NoProfile", "-Command", "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($args[0])", text], 30)["ok"]
    if platform.system() == "Darwin" and _exists("say"): return _run(["say", text], 30)["ok"]
    return False

def record(seconds: int = RECORD_SECONDS) -> Optional[Path]:
    seconds = max(1, min(int(seconds), 60)); filename = VOICE_DIR / f"input_{int(time.time()*1000)}.wav"
    if not _exists("termux-microphone-record"): return None
    result = _run(["termux-microphone-record", "-l", str(seconds), "-f", str(filename)], seconds + 10)
    return filename if result["ok"] and filename.exists() and filename.stat().st_size >= 100 else None

def termux_speech_to_text() -> dict[str, Any]:
    """Use Android's native speech recognizer through Termux:API; real microphone STT."""
    if not _exists("termux-speech-to-text"):
        return {"ok": False, "provider": "termux-speech-to-text", "error": "Termux:API speech command unavailable"}
    result = _run(["termux-speech-to-text"], 90)
    if not result["ok"] or not result["stdout"]:
        return {"ok": False, "provider": "termux-speech-to-text", "error": result["stderr"] or "speech recognition returned no text"}
    return {"ok": True, "text": result["stdout"], "provider": "termux-speech-to-text"}

def _faster_whisper(audio: Path) -> dict[str, Any]:
    model = os.getenv("NEXO_WHISPER_MODEL", "").strip()
    if not model or importlib.util.find_spec("faster_whisper") is None: return {"ok": False, "error": "faster-whisper/model not configured"}
    try:
        from faster_whisper import WhisperModel
        engine = WhisperModel(model, device=os.getenv("NEXO_WHISPER_DEVICE", "cpu"), compute_type=os.getenv("NEXO_WHISPER_COMPUTE", "int8"))
        segments, info = engine.transcribe(str(audio), vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"ok": bool(text), "text": text, "provider": "faster-whisper", "language": getattr(info, "language", None)}
    except Exception as exc: return {"ok": False, "error": f"faster-whisper: {exc}"}

def _whisper_cpp(audio: Path) -> dict[str, Any]:
    model = os.getenv("NEXO_WHISPER_MODEL", "").strip(); binary = next((x for x in ("whisper-cli","whisper-cpp","whisper") if _exists(x)), None)
    if not model or not binary: return {"ok": False, "error": "whisper.cpp/model not configured"}
    result = _run([binary,"-m",model,"-f",str(audio),"-nt","-np"],120)
    if not result["ok"]: return {"ok":False,"error":result["stderr"] or "whisper.cpp failed"}
    return {"ok":bool(result["stdout"]),"text":re.sub(r"\s+"," ",result["stdout"]).strip(),"provider":"whisper.cpp"}

def speech_to_text(audio_file: Path | str | None = None) -> dict[str, Any]:
    if audio_file is None:
        return termux_speech_to_text()
    path = Path(audio_file)
    if not path.exists(): return {"ok":False,"provider":"none","error":"audio file missing"}
    for adapter in (_faster_whisper,_whisper_cpp):
        result=adapter(path)
        if result.get("ok"): return result
    return {"ok":False,"provider":"none","error":"No configured STT engine succeeded"}

def normalize(text: str) -> str: return re.sub(r"\s+"," ",(text or "").strip().lower())
def is_wake_word(text: str) -> bool:
    value=normalize(text); return any(value==w or value.startswith(w+" ") for w in WAKE_WORDS)
def remove_wake_word(text: str) -> str:
    value=text or ""
    for word in WAKE_WORDS: value=re.sub(re.escape(word),"",value,flags=re.I)
    return value.strip(" ,.!?;:")

def _execute_voice_tool(name: str,args: dict[str,Any],*,owner: bool,user_id: int|str|None=None,confirmation: bool=False)->dict[str,Any]:
    serialized=json.dumps(args,ensure_ascii=False).lower()
    if any(term in name.lower() or term in serialized for term in SENSITIVE_TERMS):
        if not owner: return {"ok":False,"verified":False,"requires_confirmation":True,"error":"owner_authorization_required"}
        if not confirmation: return {"ok":False,"verified":False,"requires_confirmation":True,"error":"explicit_confirmation_required"}
    result=execute_registered_tool(name,args,owner=owner,user_id=user_id); result.setdefault("verified",False); return result

def execute_via_nexo(text: str,*,owner: bool=True,user_id:int|str|None=None,confirmation:bool=False,planner:ExecutivePlanner|None=None)->dict[str,Any]:
    task=create_task(text); planner=planner or ExecutivePlanner(LLAMA_URL); observed=[]
    def executor(name,args,**kw):
        result=_execute_voice_tool(name,args,owner=owner,user_id=user_id,confirmation=confirmation); observed.append({"name":name,"args":args,"result":result}); return result
    messages=[{"role":"system","content":"You are NEXO's voice execution planner. Use only registered tools. Plan multi-step tasks when needed. Never claim success unless tool result has verified=true. Unsupported actions must be reported truthfully."},{"role":"user","content":text}]
    answer=planner.run(text,messages,schemas(),executor,owner=owner,user_id=user_id,max_steps=6)
    requires=any(x["result"].get("requires_confirmation") for x in observed)
    verified=bool(observed) and all(x["result"].get("verified") is True for x in observed) and not requires
    return {"ok":bool(observed) and not requires,"verified":verified,"response":answer,"agent":task.agent,"intent":task.intent,"tools":observed,"requires_confirmation":requires}

class NexoVoiceAssistant:
    def __init__(self,stt:Callable= speech_to_text,tts:Callable[[str],bool]=speak,recorder:Callable[[int],Optional[Path]]=record): self.stt,self.tts,self.recorder=stt,tts,recorder
    def process_text(self,text:str,owner:bool=True,user_id:int|str|None=None,confirmation:bool=False,planner:ExecutivePlanner|None=None)->VoiceResult:
        text=(text or "").strip()
        if not text:return VoiceResult(False,stage="input")
        if is_wake_word(text):
            text=remove_wake_word(text)
            if not text:
                response="Yes, how can I help you?"; spoken=self.tts(response)
                return VoiceResult(True,response=response,stage="wake",provider="text",verified=spoken,details={"tts_verified":spoken})
        outcome=execute_via_nexo(text,owner=owner,user_id=user_id,confirmation=confirmation,planner=planner)
        response="I need your explicit confirmation before I do that." if outcome["requires_confirmation"] else outcome["response"]
        spoken=self.tts(response)
        return VoiceResult(outcome["ok"],text=text,response=response,stage="execute",provider="nexo-manager",verified=outcome["verified"] and spoken,details=outcome|{"tts_verified":spoken})
    def listen_once(self,seconds:int=RECORD_SECONDS,owner:bool=True,user_id:int|str|None=None,confirmation:bool=False)->VoiceResult:
        # Android native STT is preferred because it captures from the real microphone directly.
        stt=self.stt(None) if self.stt is speech_to_text else None
        if stt is None:
            audio=self.recorder(seconds)
            if not audio:return VoiceResult(False,stage="record",details={"error":"microphone recording failed"})
            stt=self.stt(audio)
        if not stt.get("ok"):return VoiceResult(False,stage="stt",provider=stt.get("provider","none"),details=stt)
        result=self.process_text(stt.get("text",""),owner=owner,user_id=user_id,confirmation=confirmation); result.details["stt"]=stt; return result
    def run_forever(self,owner:bool=True,user_id:int|str|None=None)->None:
        """Persistent Android loop: block on native mic STT, stay idle until 'Hey Nexo'."""
        while True:
            stt=termux_speech_to_text()
            if not stt.get("ok") or not is_wake_word(stt.get("text","")): continue
            command=remove_wake_word(stt["text"])
            if not command:
                spoken=self.tts("Yes, how can I help you?")
                if not spoken: time.sleep(1)
                continue
            self.process_text(command,owner=owner,user_id=user_id)

def self_test()->dict[str,Any]:
    return {"termux_microphone_stt":_exists("termux-speech-to-text"),"termux_record":_exists("termux-microphone-record"),"tts":_exists("termux-tts-speak") or _exists("say") or _exists("powershell"),"faster_whisper_installed":importlib.util.find_spec("faster_whisper") is not None,"whisper_cli_installed":any(_exists(x) for x in ("whisper-cli","whisper-cpp","whisper")),"wake_model_configured":bool(os.getenv("NEXO_WAKE_MODEL")),"llama_url":LLAMA_URL,"registered_tools":len(schemas())}

def listen(seconds:int=RECORD_SECONDS)->dict[str,Any]:return NexoVoiceAssistant().listen_once(seconds).as_dict()
def voice_session()->dict[str,Any]:return NexoVoiceAssistant().listen_once().as_dict()
if __name__=="__main__":print(json.dumps(self_test(),indent=2,ensure_ascii=False))
