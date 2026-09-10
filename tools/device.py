from __future__ import annotations

import subprocess


def run(action: str) -> dict:
    commands = {"wifi_on":["termux-wifi-enable","true"],"wifi_off":["termux-wifi-enable","false"],"torch_on":["termux-torch","on"],"torch_off":["termux-torch","off"],"battery":["termux-battery-status"]}
    try:
        p = subprocess.run(commands[action], capture_output=True, text=True, timeout=15, check=False)
        return {"ok": p.returncode == 0, "output": p.stdout[-2000:], "error": p.stderr[-1000:]}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
