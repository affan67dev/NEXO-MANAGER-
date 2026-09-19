#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUN_DIR = Path.home() / ".nexo" / "run"
PID_FILE = RUN_DIR / "alex.pid"
LOG_FILE = RUN_DIR / "alex.log"
DISABLE_FILE = RUN_DIR / "autostart.disabled"


def _pid() -> int | None:
    try:
        value = int(PID_FILE.read_text(encoding="utf-8").strip())
        return value if value > 0 else None
    except (OSError, ValueError):
        return None


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def status() -> int:
    pid = _pid()
    print(json.dumps({"running": _alive(pid), "pid": pid, "log": str(LOG_FILE),
                      "autostart_disabled": DISABLE_FILE.exists()}, indent=2))
    return 0


def start() -> int:
    pid = _pid()
    if _alive(pid):
        print(f"ALEX already running (pid {pid})")
        return 0
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_FILE.open("a", encoding="utf-8")
    env = os.environ.copy()
    env.setdefault("NEXO_VOICE_IDLE_POLLING", "false")
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "voice_assistant.py")],
        cwd=REPO, env=env, stdin=subprocess.DEVNULL,
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
    )
    PID_FILE.write_text(str(proc.pid) + "\n", encoding="utf-8")
    time.sleep(0.3)
    if not _alive(proc.pid):
        PID_FILE.unlink(missing_ok=True)
        print("ERROR: ALEX exited during startup", file=sys.stderr)
        return 1
    print(f"ALEX started (pid {proc.pid})")
    return 0


def stop() -> int:
    pid = _pid()
    if not _alive(pid):
        PID_FILE.unlink(missing_ok=True)
        print("ALEX is not running")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"ERROR: stop failed: {exc}", file=sys.stderr)
        return 1
    for _ in range(20):
        if not _alive(pid):
            PID_FILE.unlink(missing_ok=True)
            print("ALEX stopped")
            return 0
        time.sleep(0.1)
    print("ERROR: ALEX did not stop cleanly", file=sys.stderr)
    return 1


def wake() -> int:
    pid = _pid()
    if not _alive(pid):
        print("ERROR: ALEX is not running; use start first", file=sys.stderr)
        return 1
    if hasattr(signal, "SIGUSR1"):
        os.kill(pid, signal.SIGUSR1)
        print("ALEX wake request sent. Say: Hey Alex")
        return 0
    print("ERROR: this platform has no supported wake signal", file=sys.stderr)
    return 1


def autostart_on() -> int:
    DISABLE_FILE.unlink(missing_ok=True)
    print("ALEX autostart enabled")
    return 0


def autostart_off() -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    DISABLE_FILE.write_text("disabled\n", encoding="utf-8")
    print("ALEX autostart disabled")
    return 0


def logs() -> int:
    if not LOG_FILE.exists():
        print("No ALEX log yet.")
        return 0
    print(LOG_FILE.read_text(encoding="utf-8", errors="replace")[-12000:])
    return 0


def bootstrap(ready: bool = False) -> int:
    command = [sys.executable, str(REPO / "scripts" / "bootstrap_nexo.py")]
    if ready:
        command.append("--ready")
    return subprocess.call(command, cwd=REPO)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe ALEX runtime controller")
    parser.add_argument(
        "command",
        choices=("setup", "bootstrap", "start", "stop", "restart", "status", "logs",
                 "wake", "autostart-on", "autostart-off"),
    )
    args = parser.parse_args()
    if args.command == "setup":
        return bootstrap(ready=True)
    if args.command == "bootstrap":
        return bootstrap()
    if args.command == "start":
        return start()
    if args.command == "stop":
        return stop()
    if args.command == "restart":
        stop()
        return start()
    if args.command == "status":
        return status()
    if args.command == "logs":
        return logs()
    if args.command == "autostart-on":
        return autostart_on()
    if args.command == "autostart-off":
        return autostart_off()
    return wake()


if __name__ == "__main__":
    raise SystemExit(main())
