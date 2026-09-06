from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def maintenance_status() -> dict:
    config = json.loads((ROOT/"config/maintenance.json").read_text())
    now = datetime.now(ZoneInfo(config["timezone"]))
    start = config["window"]["start"]
    end = config["window"]["end"]
    current = now.strftime("%H:%M")
    return {
        "enabled":config["enabled"],
        "timezone":config["timezone"],
        "current_time":current,
        "window":f"{start}-{end}",
        "note":"Scheduler integration is required before automatic execution."
    }
