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
PM2_NAMES = ("nexo-backend", "nexo-llama")


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, check=check)


def hardware() -> dict[str, object]:
    info: dict[str, object] = {
        "os": platform.system(), "release": platform.release(), "machine": platform.machine(),
        "python": platform.python_version(), "cpu_count": os.cpu_count() or 1,
        "ram_bytes": None, "gpu": [],
    }
    try:
        import psutil
        info["ram_bytes"] = int(psutil.virtual_memory().total)
    except Exception:
        pass
    probes: list[list[str]] = []
    if shutil.which("nvidia-smi"):
        probes.append(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    if shutil.which("rocm-smi"):
        probes.append(["rocm-smi", "--showproductname"])
    if platform.system() == "Darwin" and shutil.which("system_profiler"):
        probes.append(["system_profiler", "SPDisplaysDataType"])
    if platform.system() == "Windows" and shutil.which("powershell"):
        probes.append(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"])
    for cmd in probes:
        try:
            result = run(cmd)
            if result.returncode == 0:
                info["gpu"] += [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except OSError:
            pass
    info["gpu"] = info["gpu"][:8]
    return info


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
        str(REPO / "llama.cpp" / "build" / "bin" / "llama-server"),
    ]
    for candidate in candidates:
        found = _existing_file(candidate)
        if found:
            return found
    return None


def find_model() -> str | None:
    configured = _existing_file(os.getenv("NEXO_MODEL_PATH", "").strip())
    if configured and configured.lower().endswith(".gguf"):
        return configured
    roots = [REPO / "models", Path.home() / "models"]
    if os.getenv("PREFIX"):
        roots.append(Path("/sdcard/Download"))
    # Deliberately non-recursive: scanning all shared storage is expensive on phones.
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for found in root.glob("*.gguf"):
                if found.is_file():
                    return str(found.resolve())
        except OSError:
            continue
    return None


def init_sqlite() -> None:
    # memory_engine.py owns schema creation/migrations. Bootstrap only verifies that
    # the database can be opened; it never rewrites or migrates existing data.
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB, timeout=10) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("SELECT 1")


def ensure_venv() -> Path:
    python_path = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python_path.exists():
        VENV.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    if not python_path.is_file():
        raise RuntimeError(f"virtual environment Python is missing: {python_path}")
    return python_path


def dependency_manifest() -> Path:
    if os.getenv("PREFIX"):
        termux = REPO / "requirements-nexo-termux.txt"
        if termux.is_file():
            return termux
    manifest = REPO / "requirements-nexo.txt"
    if not manifest.is_file():
        raise RuntimeError("requirements-nexo.txt is missing")
    return manifest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_dependencies(py: Path, manifest: Path) -> bool:
    digest = file_sha256(manifest)
    marker = STATE / "dependencies.sha256"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == digest:
        return False
    subprocess.run([str(py), "-m", "pip", "install", "-r", str(manifest)], check=True)
    STATE.mkdir(parents=True, exist_ok=True)
    marker.write_text(digest + "\n", encoding="utf-8")
    return True


def detect_pm2() -> dict[str, object]:
    pm2 = shutil.which("pm2")
    result: dict[str, object] = {"available": bool(pm2), "processes": {}}
    if not pm2:
        return result
    for name in PM2_NAMES:
        try:
            result["processes"][name] = run([pm2, "describe", name]).returncode == 0
        except OSError:
            result["processes"][name] = False
    return result


def wizard() -> str:
    if not sys.stdin.isatty():
        return "personal"
    value = input("NEXO profile [personal/shared] (personal): ").strip().lower() or "personal"
    return value if value in {"personal", "shared"} else "personal"


def desktop_shortcut() -> bool:
    if platform.system() != "Linux":
        return False
    desktop = Path(os.getenv("XDG_DESKTOP_DIR", str(Path.home() / "Desktop")))
    if not desktop.is_dir():
        return False
    target = desktop / "NEXO.desktop"
    target.write_text(
        "[Desktop Entry]\nType=Application\nName=NEXO\nTerminal=true\n"
        f"Exec={REPO / 'bootstrap.sh'}\nPath={REPO}\n",
        encoding="utf-8",
    )
    target.chmod(0o755)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Idempotent NEXO one-click bootstrap")
    parser.add_argument("--no-install", action="store_true")
    parser.add_argument("--wizard", action="store_true")
    parser.add_argument("--desktop-shortcut", action="store_true")
    args = parser.parse_args()

    if not (REPO / ".git").exists():
        print("ERROR: run from a NEXO checkout", file=sys.stderr)
        return 2
    try:
        hw = hardware()
        llama = find_llama()
        model = find_model()
        init_sqlite()
        py = ensure_venv()
        manifest = dependency_manifest()
        installed = False if args.no_install else install_dependencies(py, manifest)
        profile = wizard() if args.wizard else "personal"
        shortcut = desktop_shortcut() if args.desktop_shortcut else False
        STATE.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 2, "repo": str(REPO), "hardware": hw,
            "python": {"executable": str(py), "venv": str(VENV)},
            "dependency_manifest": str(manifest), "dependencies_changed": installed,
            "llama_server": llama, "model": model,
            "telegram_env_file": str(ENV_FILE) if ENV_FILE.exists() else None,
            "pm2": detect_pm2(), "profile": profile, "desktop_shortcut": shortcut,
        }
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, CONFIG)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print("NEXO bootstrap: PASS")
    print(f"Platform: {hw['os']} / {hw['machine']}")
    print(f"Python environment: {py}")
    print(f"SQLite: {DB}")
    print(f"Dependency manifest: {manifest}")
    print(f"Dependencies installed: {installed}")
    print(f"llama-server: {llama or 'not detected; existing install preserved'}")
    print(f"GGUF model: {model or 'not detected; configure NEXO_MODEL_PATH when available'}")
    print(f"Telegram config: {'detected' if ENV_FILE.exists() else 'not configured'}")
    print(f"PM2: {detect_pm2()}")
    print(f"Setup state: {CONFIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
