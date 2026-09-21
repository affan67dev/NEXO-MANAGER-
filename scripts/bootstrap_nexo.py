#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".nexo" / "setup"
CONFIG = STATE / "runtime.json"
VENV = STATE / "venv"
ENV_FILE = Path.home() / ".nexo.env"
DB = REPO / "data" / "memory.db"
MVB_MANIFEST = REPO / "requirements-nexo-mvb.txt"
FULL_MANIFEST = REPO / "requirements-nexo.txt"
# Historical PM2 process names are preserved for Termux compatibility. The
# repository no longer assumes that the second process is a local LLM server.
PM2_NAMES = ("nexo-backend", "nexo-llama")
TERMUX_COMMANDS = (
    "termux-speech-to-text", "termux-microphone-record", "termux-tts-speak",
    "termux-toast", "termux-screenshot", "termux-battery-status",
)


def is_termux() -> bool:
    prefix = os.getenv("PREFIX", "").strip()
    return bool(prefix) and Path(prefix).is_dir()


def run(cmd: list[str], check: bool = False, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, check=check, timeout=timeout)


def _detect_ram_bytes() -> int | None:
    try:
        if Path("/proc/meminfo").is_file():
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    try:
        import psutil
        return int(psutil.virtual_memory().total)
    except Exception:
        return None


def hardware() -> dict[str, object]:
    return {
        "os": platform.system(), "release": platform.release(), "machine": platform.machine(),
        "python": platform.python_version(), "cpu_count": os.cpu_count() or 1,
        "ram_bytes": _detect_ram_bytes(), "gpu": [], "termux": is_termux(),
    }


def init_sqlite() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB, timeout=10) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("SELECT 1")


def ensure_venv() -> Path:
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required")
    python_path = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python_path.exists():
        VENV.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    return python_path


def setup_python() -> tuple[Path, bool]:
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required")
    if is_termux():
        return Path(sys.executable).resolve(), False
    return ensure_venv(), True


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_missing_manifest(py: Path, manifest: Path, marker_name: str) -> bool:
    digest = file_sha256(manifest)
    marker = STATE / marker_name
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == digest:
        return False
    subprocess.run([str(py), "-m", "pip", "install", "-r", str(manifest)], check=True, timeout=900)
    STATE.mkdir(parents=True, exist_ok=True)
    marker.write_text(digest + "\n", encoding="utf-8")
    return True


def detect_python_modules() -> dict[str, bool]:
    modules = ("requests", "psutil", "pydantic", "httpx", "dotenv", "telegram")
    return {name: __import__(name) is not None for name in modules if _module_available(name)}


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def detect_termux_api() -> dict[str, bool]:
    return {name: bool(shutil.which(name)) for name in TERMUX_COMMANDS}


def detect_pm2() -> dict[str, object]:
    pm2 = shutil.which("pm2")
    result: dict[str, object] = {"available": bool(pm2), "processes": {}}
    if not pm2:
        return result
    for name in PM2_NAMES:
        try:
            result["processes"][name] = run([pm2, "describe", name]).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            result["processes"][name] = False
    return result


def ensure_env_template() -> tuple[bool, list[str]]:
    created = False
    if not ENV_FILE.exists():
        example = REPO / ".nexo.env.example"
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        if example.is_file():
            ENV_FILE.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            ENV_FILE.write_text(
                "LLM_PROVIDER=openrouter\nLLM_API_KEY=\nLLM_MODEL=\n"
                "LLM_BASE_URL=https://openrouter.ai/api/v1\n",
                encoding="utf-8",
            )
        try:
            ENV_FILE.chmod(0o600)
        except OSError:
            pass
        created = True
    missing: list[str] = []
    values: dict[str, str] = {}
    try:
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    except OSError:
        return created, ["~/.nexo.env"]
    for key in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL"):
        if not values.get(key):
            missing.append(key)
    for key, value in values.items():
        if value and key not in os.environ:
            os.environ[key] = value
    return created, missing


def install_alex_command() -> bool:
    if not is_termux():
        return False
    prefix_bin = Path(os.getenv("PREFIX", "")) / "bin"
    if not prefix_bin.is_dir():
        return False
    target = prefix_bin / "alex"
    content = f'#!/data/data/com.termux/files/usr/bin/sh\nexec "{sys.executable}" "{REPO / "scripts" / "alexctl.py"}" "$@"\n'
    try:
        target.write_text(content, encoding="utf-8")
        target.chmod(0o755)
        return True
    except OSError:
        return False


def install_autostart_hook() -> bool:
    if not is_termux():
        return False
    bashrc = Path.home() / ".bashrc"
    marker = "# >>> NEXO ALEX AUTOSTART >>>"
    end = "# <<< NEXO ALEX AUTOSTART <<<"
    block = (
        f"\n{marker}\n"
        f'if [ "[object Object]" = "true" ] && [ ! -f "$HOME/.nexo/run/autostart.disabled" ]; then\n'
        f'  alex start >/dev/null 2>&1 || true\n'
        f"fi\n{end}\n"
    )
    try:
        existing = bashrc.read_text(encoding="utf-8") if bashrc.exists() else ""
        if marker in existing:
            return False
        bashrc.parent.mkdir(parents=True, exist_ok=True)
        bashrc.write_text(existing.rstrip() + block, encoding="utf-8")
        return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Idempotent ALEX/NEXO Android-aware bootstrap")
    parser.add_argument("--no-install", action="store_true")
    parser.add_argument("--full-deps", action="store_true", help="install the full dependency manifest; not recommended for Android MVB")
    parser.add_argument("--enable-autostart", action="store_true")
    args = parser.parse_args()
    if not (REPO / ".git").exists():
        print("ERROR: run from a NEXO checkout", file=sys.stderr)
        return 2
    try:
        hw = hardware()
        py, owns_venv = setup_python()
        init_sqlite()
        env_created, missing_env = ensure_env_template()
        if args.no_install:
            installed = False
            manifest = MVB_MANIFEST if is_termux() else FULL_MANIFEST
        else:
            manifest = FULL_MANIFEST if args.full_deps else (MVB_MANIFEST if is_termux() else FULL_MANIFEST)
            installed = install_missing_manifest(py, manifest, "dependencies.sha256")
        api = detect_termux_api()
        pm2 = detect_pm2() if is_termux() else {"available": False, "processes": {}}
        alex_command = install_alex_command()
        autostart = install_autostart_hook() if args.enable_autostart and alex_command else False
        STATE.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 5, "repo": str(REPO), "hardware": hw,
            "python": {"executable": str(py), "venv": str(VENV) if owns_venv else None},
            "dependency_profile": "full" if args.full_deps else ("android-mvb" if is_termux() else "full"),
            "dependency_manifest": str(manifest), "dependencies_changed": installed,
            "telegram_env_file": str(ENV_FILE) if ENV_FILE.exists() else None,
            "llm": {"provider": os.getenv("LLM_PROVIDER", ""), "configured": bool(os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL"))},
            "termux_api": api, "pm2": pm2, "alex_command": alex_command, "autostart_hook_installed": autostart,
            "env_created": env_created, "missing_env": missing_env,
        }
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, CONFIG)
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print("ALEX/NEXO bootstrap: PASS")
    print(f"Platform: {hw['os']} / {hw['machine']}")
    print(f"Android/Termux: {is_termux()}")
    print(f"Python: {py}")
    print(f"SQLite: PASS ({DB})")
    print(f"MVB dependencies: {'installed/updated' if installed else 'already present or skipped'}")
    print(f"Termux:API: {', '.join(k for k,v in api.items() if v) if is_termux() else 'not applicable'}")
    print(f"LLM provider: {os.getenv('LLM_PROVIDER') or 'not loaded in process'}")
    print(f"LLM config: {'ready' if not missing_env else 'MISSING ' + ', '.join(missing_env)}")
    print(f"Telegram env: {'present' if ENV_FILE.exists() else 'not present'}")
    print(f"PM2 compatibility state: {pm2}")
    print(f"ALEX command: {'installed as alex' if alex_command else 'use python scripts/alexctl.py'}")
    print(f"Autostart: {'enabled' if autostart else 'not changed'}")
    print(f"Setup state: {CONFIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
