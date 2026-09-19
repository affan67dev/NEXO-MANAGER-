"""Controlled Android/Termux capability layer for ALEX. No arbitrary shell execution."""
from __future__ import annotations
import hashlib, shutil, subprocess, time
from pathlib import Path
from typing import Any
from core.operational_history import record_event

SCREEN_DIR=Path.home()/"NEXO"/"screen"; SCREEN_DIR.mkdir(parents=True,exist_ok=True)

def _run(command:list[str],timeout:int=20)->dict[str,Any]:
    try:
        p=subprocess.run(command,capture_output=True,text=True,timeout=timeout,check=False)
        return {"ok":p.returncode==0,"stdout":p.stdout.strip(),"stderr":p.stderr.strip(),"code":p.returncode}
    except (OSError,subprocess.TimeoutExpired) as exc:
        return {"ok":False,"stdout":"","stderr":str(exc),"code":-1}

def _exists(name:str)->bool:return shutil.which(name) is not None

def capabilities()->dict[str,Any]:
    return {"termux_api":_exists("termux-battery-status"),"screen_capture":_exists("termux-screenshot"),
            "toast":_exists("termux-toast"),"tts":_exists("termux-tts-speak"),
            "stt":_exists("termux-speech-to-text"),"microphone_record":_exists("termux-microphone-record"),
            "ocr":_exists("tesseract")}

def capture_screen()->dict[str,Any]:
    if not _exists("termux-screenshot"):
        return {"ok":False,"verified":False,"available":False,"error":"screen_capture_unavailable"}
    target=SCREEN_DIR/f"screen_{int(time.time()*1000)}.png"
    result=_run(["termux-screenshot","-p",str(target)],30)
    if not result["ok"] or not target.exists() or target.stat().st_size==0:
        return {"ok":False,"verified":False,"available":True,"error":"screen_capture_failed",
                "detail":result["stderr"] or result["stdout"]}
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    record_event("screen_capture",{"timestamp":time.time(),"sha256":digest})
    return {"ok":True,"verified":True,"available":True,"path":str(target),"sha256":digest}

def analyze_screen()->dict[str,Any]:
    captured=capture_screen()
    if not captured.get("ok"): return captured
    path=Path(captured["path"])
    observation={"screen_captured":True,"observed":[],"inferred":[],"uncertain":[]}
    if _exists("tesseract"):
        result=_run(["tesseract",str(path),"stdout","--psm","6"],30)
        if result["ok"] and result["stdout"]:
            observation["observed"]=[x.strip() for x in result["stdout"].splitlines() if x.strip()][:80]
        else: observation["uncertain"].append("OCR did not return readable text.")
    else:
        observation["uncertain"].append("Visual OCR is unavailable because tesseract is not installed.")
    observation["capture_verified"]=True
    record_event("screen_analysis",{"observation":observation})
    return {"ok":True,"verified":True,"path":str(path),**observation}

def toast_state(state: str) -> dict[str, Any]:
    labels = {
        "WAKE_DETECTED": "ALEX • ●",
        "LISTENING": "ALEX • Listening…",
        "PROCESSING": "ALEX • Thinking…",\n        "UNDERSTANDING": "ALEX • Understanding…",\n        "ANALYSING": "ALEX • Analysing…",\n        "DECIDING": "ALEX • Deciding…",\n        "PLANNING": "ALEX • Planning…",\n        "AWAITING_CONFIRMATION": "ALEX • Confirm?",\n        "EXECUTING": "ALEX • Executing…",\n        "VERIFYING": "ALEX • Verifying…",
        "SPEAKING": "ALEX • Speaking…",
        "ERROR": "ALEX • Something went wrong",
    }
    if state not in labels:
        return {"ok": False, "verified": False, "error": "invalid_voice_state"}
    if not _exists("termux-toast"):
        return {"ok": False, "verified": False, "available": False, "error": "toast_unavailable"}
    result = _run(["termux-toast", "-g", "top", labels[state]], 10)
    return {"ok": result["ok"], "verified": result["ok"], "state": state, "label": labels[state]}


def show_voice_error() -> dict[str, Any]:
    return toast_state("ERROR")


APP_PACKAGES = {
    "youtube": "com.google.android.youtube",
    "telegram": "org.telegram.messenger",
    "whatsapp": "com.whatsapp",
    "chrome": "com.android.chrome",
    "instagram": "com.instagram.android",
    "settings": "com.android.settings",
    "calculator": "com.google.android.calculator",
}

def get_foreground_package() -> dict[str, Any]:
    """Read the actual resumed Android package when the shell exposes it."""
    for command in (
        ["dumpsys", "activity", "activities"],
        ["dumpsys", "activity", "top"],
    ):
        if not _exists(command[0]):
            continue
        result = _run(command, 10)
        if not result["ok"]:
            continue
        for line in result["stdout"].splitlines():
            if "mResumedActivity" in line or "mFocusedApp" in line:
                import re
                match = re.search(r"([A-Za-z0-9_]+\.[A-Za-z0-9_.]+)/(?:[A-Za-z0-9_.$]+)", line)
                if match:
                    return {"ok": True, "verified": True, "package": match.group(1)}
    return {"ok": False, "verified": False, "error": "foreground_package_unavailable"}

def launch_app(app: str) -> dict[str, Any]:
    key = (app or "").strip().lower()
    package = APP_PACKAGES.get(key)
    if not package:
        return {"ok": False, "verified": False, "error": "app_not_allowlisted", "app": key}
    if not _exists("monkey"):
        return {"ok": False, "verified": False, "error": "android_launcher_unavailable", "app": key}
    result = _run(["monkey", "-p", package, "1"], 15)
    if not result["ok"]:
        return {"ok": False, "verified": False, "error": "app_launch_failed", "detail": result["stderr"] or result["stdout"], "app": key}
    foreground = get_foreground_package()
    verified = foreground.get("package") == package
    return {"ok": verified, "verified": verified, "app": key, "package": package,
            "foreground": foreground.get("package"), "error": None if verified else "foreground_verification_failed"}
