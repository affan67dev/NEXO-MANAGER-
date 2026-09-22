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
        "PROCESSING": "ALEX • Thinking…",
        "UNDERSTANDING": "ALEX • Understanding…",
        "ANALYSING": "ALEX • Analysing…",
        "DECIDING": "ALEX • Deciding…",
        "PLANNING": "ALEX • Planning…",
        "AWAITING_CONFIRMATION": "ALEX • Confirm?",
        "EXECUTING": "ALEX • Executing…",
        "VERIFYING": "ALEX • Verifying…",
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

def inspect_ui_tree() -> dict[str, Any]:
    """Return the current accessibility tree when Android exposes uiautomator."""
    if not _exists("uiautomator"):
        return {"ok": False, "verified": False, "error": "uiautomator_unavailable"}
    target = SCREEN_DIR / "ui.xml"
    result = _run(["uiautomator", "dump", str(target)], 15)
    if not result["ok"] or not target.exists():
        return {"ok": False, "verified": False, "error": "ui_tree_dump_failed",
                "detail": result["stderr"] or result["stdout"]}
    try:
        xml = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "verified": False, "error": "ui_tree_read_failed", "detail": str(exc)}
    if not xml.strip():
        return {"ok": False, "verified": False, "error": "ui_tree_empty"}
    return {"ok": True, "verified": True, "path": str(target), "xml": xml}


def semantic_ui_action(action: str, target: str = "", text: str = "") -> dict[str, Any]:
    """Perform bounded semantic UI actions using the current uiautomator tree."""
    action = (action or "").strip().lower()
    if action not in {"click", "type", "back", "scroll"}:
        return {"ok": False, "verified": False, "error": "unsupported_ui_action"}
    if not _exists("uiautomator") or not _exists("input"):
        return {"ok": False, "verified": False, "error": "semantic_ui_controls_unavailable"}
    if action == "back":
        result = _run(["input", "keyevent", "4"], 10)
        return {"ok": result["ok"], "verified": result["ok"], "action": action}
    if action == "scroll":
        coords = ["500", "900", "500", "300", "400"] if target.lower() != "up" else ["500", "300", "500", "900", "400"]
        result = _run(["input", "swipe", *coords], 10)
        return {"ok": result["ok"], "verified": result["ok"], "action": action, "fallback": "validated_gesture"}
    tree = inspect_ui_tree()
    if not tree.get("ok"):
        return tree
    import re as _re
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(tree.get("xml", ""))
    except ET.ParseError:
        return {"ok": False, "verified": False, "error": "ui_tree_parse_failed"}
    node = next((n for n in root.iter("node")
                 if target and (n.attrib.get("text") == target or n.attrib.get("content-desc") == target)), None)
    if node is None:
        return {"ok": False, "verified": False, "error": "semantic_target_not_found", "target": target}
    match = _re.fullmatch(r"\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]", node.attrib.get("bounds", ""))
    if not match:
        return {"ok": False, "verified": False, "error": "semantic_bounds_unavailable"}
    x1,y1,x2,y2 = map(int, match.groups())
    x,y = (x1+x2)//2, (y1+y2)//2
    if action == "click":
        result = _run(["input", "tap", str(x), str(y)], 10)
        return {"ok": result["ok"], "verified": result["ok"], "action": action, "target": target}
    if action == "type":
        if not text:
            return {"ok": False, "verified": False, "error": "type_text_required"}
        result = _run(["input", "text", text.replace(" ", "%s")], 10)
        return {"ok": result["ok"], "verified": result["ok"], "action": action, "target": target}
    return {"ok": False, "verified": False, "error": "unsupported_ui_action"}

