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

def toast_state(state:str)->dict[str,Any]:
    if state not in {"IDLE","LISTENING","PROCESSING","SPEAKING"}:
        return {"ok":False,"verified":False,"error":"invalid_voice_state"}
    if not _exists("termux-toast"):
        return {"ok":False,"verified":False,"available":False,"error":"toast_unavailable"}
    result=_run(["termux-toast","-g","top",f"ALEX • {state}"],10)
    return {"ok":result["ok"],"verified":result["ok"],"state":state}
