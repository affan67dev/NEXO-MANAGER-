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
import time
from pathlib import Path
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".nexo" / "setup"
CONFIG = STATE / "runtime.json"
VENV = STATE / "venv"
ENV_FILE = Path.home() / ".nexo.env"
DB = REPO / "data" / "memory.db"
MVB_MANIFEST = REPO / "requirements-nexo-mvb.txt"
FULL_MANIFEST = REPO / "requirements-nexo.txt"
PM2_NAMES = ("nexo-backend", "nexo-llama")
TERMUX_COMMANDS = (
    "termux-speech-to-text", "termux-microphone-record", "termux-tts-speak",
    "termux-toast", "termux-screenshot", "termux-battery-status",
)
VOICE_TERMUX_COMMANDS = ("termux-speech-to-text", "termux-tts-speak", "termux-toast")


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


def _existing_file(value: str) -> str | None:
    if not value:
        return None
    try:
        path = Path(value).expanduser()
        if path.is_file():
            return str(path.resolve())
    except OSError:
        pass
    return None


def find_llama() -> str | None:
    candidates = [
        os.getenv("LLAMA_SERVER", ""), shutil.which("llama-server") or "",
        str(Path.home() / "llama.cpp" / "build" / "bin" / "llama-server"),
        str(Path.home() / "llama.cpp" / "llama-server"),
    ]
    for candidate in candidates:
        found = _existing_file(candidate)
        if found:
            return found
    return None


def find_models() -> list[str]:
    roots = [REPO / "models", Path.home() / "models"]
    if is_termux():
        roots.append(Path("/sdcard/Download"))
    configured = _existing_file(os.getenv("NEXO_MODEL_PATH", "").strip())
    found: list[str] = []
    if configured and configured.lower().endswith(".gguf"):
        found.append(configured)
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for item in root.glob("*.gguf"):
                if item.is_file() and str(item.resolve()) not in found:
                    found.append(str(item.resolve()))
        except OSError:
            continue
    return found[:50]


def find_model() -> str | None:
    models = find_models()
    return models[0] if models else None


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
    return {name: _module_available(name) for name in modules}


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def detect_termux_api() -> dict[str, bool]:
    return {name: bool(shutil.which(name)) for name in TERMUX_COMMANDS}


def ensure_termux_api() -> tuple[dict[str, bool], bool]:
    before = detect_termux_api()
    if not is_termux() or all(before.get(name, False) for name in VOICE_TERMUX_COMMANDS):
        return before, False
    pkg = shutil.which("pkg")
    if not pkg:
        return before, False
    subprocess.run([pkg, "install", "-y", "termux-api"], cwd=REPO, check=False, timeout=180)
    after = detect_termux_api()
    return after, after != before


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


def start_existing_pm2(pm2: dict[str, object]) -> dict[str, bool]:
    if not pm2.get("available"):
        return {}
    binary = shutil.which("pm2")
    if not binary:
        return {}
    started: dict[str, bool] = {}
    processes = pm2.get("processes", {})
    for name in PM2_NAMES:
        if not processes.get(name):
            continue
        if pm2_online(name):
            started[name] = False
            continue
        result = run([binary, "start", name, "--update-env"], timeout=30)
        started[name] = result.returncode == 0
    return started


def pm2_online(name: str) -> bool:
    binary = shutil.which("pm2")
    if not binary:
        return False
    try:
        result = run([binary, "jlist"], timeout=20)
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout or "[]")
        return any(
            item.get("name") == name and item.get("pm2_env", {}).get("status") == "online"
            for item in data
        )
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False


def check_llama_health(url: str = "http://127.0.0.1:8080/health", timeout: int = 5) -> bool:
    try:
        with urlopen(Request(url, method="GET"), timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            return payload.get("ok") is True
    except Exception:
        return False


def load_env_file() -> tuple[bool, list[str]]:
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
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return created, ["~/.nexo.env"]
    if not values.get("LLM_PROVIDER"):
        missing.append("LLM_PROVIDER")
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
        'if [ ! -f "$HOME/.nexo/run/autostart.disabled" ]; then\n'
        "  alex start >/dev/null 2>&1 || true\n"
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


def start_alex() -> bool:
    controller = REPO / "scripts" / "alexctl.py"
    result = subprocess.run([sys.executable, str(controller), "start"], cwd=REPO, text=True, capture_output=True, timeout=30)
    return result.returncode == 0


def build_state(hw: dict[str, object], py: Path, owns_venv: bool, manifest: Path,
                installed: bool, llama: str | None, models: list[str],
                api: dict[str, bool], pm2: dict[str, object], started: dict[str, bool],
                missing_env: list[str], alex_command: bool, autostart: bool,
                ready: bool, failures: list[str]) -> dict[str, object]:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    local_provider = provider in {"local", "llama", "llama.cpp", "llama-server"}
    return {
        "schema_version": 5, "repo": str(REPO), "hardware": hw,
        "python": {"executable": str(py), "venv": str(VENV) if owns_venv else None},
        "dependency_profile": "full" if not is_termux() else "android-mvb",
        "dependency_manifest": str(manifest), "dependencies_changed": installed,
        "llama_server": llama, "models": models,
        "llm": {
            "provider": provider or None, "local_required": local_provider,
            "configured": bool(os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL")) if not local_provider else bool(os.getenv("LLM_MODEL") or models),
        },
        "termux_api": api, "pm2": pm2, "pm2_started": started,
        "alex_command": alex_command, "autostart_hook_installed": autostart,
        "env_created": False, "missing_env": missing_env,
        "ready": ready, "failures": failures,
        "server_health": check_llama_health() if local_provider else None,
    }


def ready_mode(py: Path, hw: dict[str, object], manifest: Path, installed: bool,
               missing_env: list[str], alex_command: bool, autostart: bool) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    local_required = provider in {"local", "llama", "llama.cpp", "llama-server"}
    llama = find_llama()
    models = find_models()
    api, _ = ensure_termux_api()
    pm2 = detect_pm2() if is_termux() else {"available": False, "processes": {}}
    started = start_existing_pm2(pm2) if is_termux() else {}
    time.sleep(1.0)

    if is_termux():
        for name in VOICE_TERMUX_COMMANDS:
            if not api.get(name, False):
                failures.append(f"Termux:API component missing: {name}")

    if missing_env:
        failures.extend(f"configuration missing: {key}" for key in missing_env)

    if local_required:
        if not llama:
            failures.append("local llama-server not detected")
        if not models:
            failures.append("local GGUF model not found")
        if llama and models and not check_llama_health():
            failures.append("llama-server /health did not return ok:true")
        if pm2.get("processes", {}).get("nexo-llama") and not pm2_online("nexo-llama"):
            failures.append("PM2 nexo-llama is not online")
    else:
        if not provider:
            failures.append("LLM_PROVIDER is not configured")
        if provider in {"openrouter", "openai", "anthropic"} and not os.getenv("LLM_API_KEY"):
            failures.append("LLM_API_KEY is not configured")
        if provider and not os.getenv("LLM_MODEL"):
            failures.append("LLM_MODEL is not configured")

    if pm2.get("processes", {}).get("nexo-backend") and not pm2_online("nexo-backend"):
        failures.append("PM2 nexo-backend is not online")

    # Do not start ALEX until required infrastructure has passed validation.
    if not failures and not start_alex():
        failures.append("ALEX runtime failed to start")

    data = build_state(hw, py, False, manifest, installed, llama, models, api, pm2, started,
                       missing_env, alex_command, autostart, not failures, failures)
    return data, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Idempotent ALEX/NEXO Android-aware bootstrap")
    parser.add_argument("--no-install", action="store_true")
    parser.add_argument("--full-deps", action="store_true", help="install the legacy full dependency manifest")
    parser.add_argument("--enable-autostart", action="store_true")
    parser.add_argument("--ready", action="store_true", help="prepare existing runtime, start services/ALEX, and verify readiness")
    args = parser.parse_args()
    if not (REPO / ".git").exists():
        print("ERROR: run from a NEXO checkout", file=sys.stderr)
        return 2
    try:
        hw = hardware()
        py, owns_venv = setup_python()
        init_sqlite()
        env_created, missing_env = load_env_file()
        if args.no_install:
            installed = False
            manifest = MVB_MANIFEST if is_termux() else FULL_MANIFEST
        else:
            manifest = FULL_MANIFEST if args.full_deps else (MVB_MANIFEST if is_termux() else FULL_MANIFEST)
            installed = install_missing_manifest(py, manifest, "dependencies.sha256")
        alex_command = install_alex_command()
        autostart = install_autostart_hook() if args.enable_autostart and alex_command else False

        if args.ready:
            data, failures = ready_mode(py, hw, manifest, installed, missing_env, alex_command, autostart)
        else:
            api = detect_termux_api()
            pm2 = detect_pm2() if is_termux() else {"available": False, "processes": {}}
            llama = find_llama()
            models = find_models()
            data = build_state(hw, py, owns_venv, manifest, installed, llama, models, api, pm2, {},
                               missing_env, alex_command, autostart, False, [])
            failures = []

        STATE.mkdir(parents=True, exist_ok=True)
        data["env_created"] = env_created
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, CONFIG)
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print("ALEX Android Setup" if args.ready else "ALEX/NEXO bootstrap")
    print("────────────────────────")
    print(f"[{'OK' if hw['termux'] else 'INFO'}] Android / Termux: {hw['termux']}")
    print(f"[OK] Python: {py}")
    print(f"[OK] Dependencies: {'installed/updated' if installed else 'already present or skipped'}")
    if hw["termux"]:
        api_ok = all(data["termux_api"].get(name, False) for name in VOICE_TERMUX_COMMANDS)
        print(f"[{'OK' if api_ok else 'FAIL'}] Termux:API")
    else:
        print("[INFO] Termux:API not applicable")
    provider = data["llm"].get("provider") or "not configured"
    print(f"[{'OK' if not missing_env else 'FAIL'}] Configuration: {provider}")
    if data["llm"].get("local_required"):
        print(f"[{'OK' if data.get('llama_server') else 'FAIL'}] llama-server: {data.get('llama_server') or 'not detected'}")
        print(f"[{'OK' if data.get('models') else 'FAIL'}] GGUF model: {len(data.get('models', []))} detected")
        print(f"[{'OK' if data.get('server_health') else 'FAIL'}] LLM health: {'ok:true' if data.get('server_health') else 'failed'}")
    else:
        print("[OK] LLM backend: " + provider)
        print("[INFO] LLM server: not required")
    print(f"[{'OK' if data.get('alex_command') else 'INFO'}] ALEX command: {'installed as alex' if data.get('alex_command') else 'use python scripts/alexctl.py'}")
    if args.ready:
        print(f"[{'OK' if data.get('pm2', {}).get('processes') else 'INFO'}] Existing PM2 runtime: {data.get('pm2', {}).get('processes', {})}")
        print(f"[{'OK' if not any('ALEX runtime' in f for f in failures) else 'FAIL'}] ALEX voice runtime")
        print(f"[{'OK' if not failures else 'FAIL'}] Health/readiness")
        if failures:
            for failure in failures:
                print(f"  - {failure}")
            print("\nALEX setup incomplete.")
            return 1
        print('\nALEX is READY.')
        print('Say: "Hey Alex"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
