"""Platform capability adapter used by NEXO's application/device controls."""
from __future__ import annotations
import os
import platform
import shutil
import subprocess
from typing import Any


def current_platform() -> str:
    system = platform.system()
    if system == "Darwin": return "macos"
    if system == "Windows": return "windows"
    if system == "Linux" and os.getenv("TERMUX_VERSION"): return "android-termux"
    if system == "Linux": return "linux"
    return system.lower()


def capabilities() -> dict[str, Any]:
    p = current_platform()
    return {
        "platform": p,
        "open_url": p == "android-termux" or p in {"windows", "macos", "linux"},
        "window_control": bool(os.getenv("NEXO_ANDROID_WINDOW_COMMAND")) if p == "android-termux" else False,
        "media_verification": False,
        "device_controls": p == "android-termux",
    }


def open_url(url: str) -> tuple[bool, str]:
    p = current_platform()
    try:
        if p == "android-termux":
            command = shutil.which("termux-open-url")
            if not command: return False, "Android URL launcher is unavailable."
            result = subprocess.run([command, url], capture_output=True, text=True, timeout=10, check=False)
            return (result.returncode == 0, result.stderr.strip() or "Destination opened." if result.returncode == 0 else "Couldn't open destination.")
        if p == "windows":
            os.startfile(url)  # type: ignore[attr-defined]
            return True, "Destination opened."
        command = "open" if p == "macos" else "xdg-open"
        if not shutil.which(command): return False, f"{command} is unavailable on this platform."
        result = subprocess.run([command, url], capture_output=True, text=True, timeout=10, check=False)
        return (result.returncode == 0, "Destination opened." if result.returncode == 0 else result.stderr.strip() or "Couldn't open destination.")
    except Exception as exc:
        return False, f"Platform launcher failed: {type(exc).__name__}"
