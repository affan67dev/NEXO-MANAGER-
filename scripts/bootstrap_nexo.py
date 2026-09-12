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


def is_termux() -> bool:
    prefix = os.getenv("PREFIX", "").strip()
    return bool(prefix) and Path(prefix).is_dir()


def run(cmd: list[str], check: bool = False, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, check=check, timeout=timeout)


def _detect_ram_bytes() -> int | None:
    try:
        import psutil
        return int(psutil.virtual_memory().total)
    except Exception:
        pass
    try:
        if Path("/proc/meminfo").is_file():
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    if platform.system() == "Darwin" and shutil.which("sysctl"):
        try:
            result = subprocess.run(["sysctl", "-n", "hw.memsize"], text=True, capture_output=True, timeout=5)
            return int(result.stdout.strip())
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return None


def hardware() -> dict[str, object]:
    info: dict[str, object] = {
        "os": platform.system(), "release": platform.release(), "machine": platform.machine(),
        "python": platform.python_version(), "cpu_count": os.cpu_count() or 1,
        "ram_bytes": _detect_ram_bytes(), "gpu": [], "termux": is_termux(),
    }
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
        except (OSError, subprocess.TimeoutExpired):
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
    if is_termux():
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
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required")
    python_path = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python_path.exists():
        VENV.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    if not python_path.is_file():
        raise RuntimeError(f"virtual environment Python is missing: {python_path}")
    return python_path


def setup_python() -> tuple[Path, bool]:
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required")
    # Android/Termux already has an established production runtime. Never create a
    # second venv or reinstall packages there as part of the desktop bootstrap.
    if is_termux():
        return Path(sys.executable).resolve(), False
    return ensure_venv(), True


def dependency_manifest() -> Path:
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
        except (OSError, subprocess.TimeoutExpired):
            result["processes"][name] = False
    return result


def wizard() -> str:
    if not sys.stdin.isatty():
        return "personal"
    value = input("NEXO profile [personal/shared] (personal): ").strip().lower() or "personal"
    return value if value in {"personal", "shared"} else "personal"


def desktop_shortcut() -> bool:
    if platform.system() != "Linux" or is_termux():
        return False
    desktop = Path(os.getenv("XDG_DESKTOP_DIR", str(Path.home() / "Desktop")))
    if not desktop.is_dir():
        return False
    target = desktop / "NEXO.desktop"
    content = (
        "[Desktop Entry]\nType=Application\nName=NEXO\nTerminal=true\n"
        f"Exec=\"{REPO / 'bootstrap.sh'}\"\nPath={REPO}\n"
    )
    if target.exists():
        try:
            return target.read_text(encoding="utf-8") == content
        except OSError:
            return False
    target.write_text(content, encoding="utf-8")
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
        py, owns_venv = setup_python()
        manifest = dependency_manifest()
        installed = False if args.no_install or not owns_venv else install_dependencies(py, manifest)
        profile = wizard() if args.wizard and not is_termux() else "personal"
        shortcut = desktop_shortcut() if args.desktop_shortcut and not is_termux() else False
        STATE.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 3, "repo": str(REPO), "hardware": hw,
            "python": {"executable": str(py), "venv": str(VENV) if owns_venv else None},
            "dependency_manifest": str(manifest), "dependencies_changed": installed,
            "llama_server": llama, "model": model,
            "telegram_env_file": str(ENV_FILE) if ENV_FILE.exists() else None,
            "pm2": detect_pm2() if is_termux() else {"available": False, "processes": {}},
            "profile": profile, "desktop_shortcut": shortcut,
        }
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, CONFIG)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: bootstrap failed: {exc}", file=sys.stderr)
        return 1
    print("NEXO bootstrap: PASS")
    print(f"Platform: {hw['os']} / {hw['machine']}")
    print(f"Android/Termux mode: {is_termux()}")
    print(f"Python environment: {py}")
    print(f"SQLite: {DB}")
    print(f"Dependency manifest: {manifest}")
    print(f"Dependencies installed: {installed}")
    print(f"llama-server: {llama or 'not detected; existing install preserved'}")
    print(f"GGUF model: {model or 'not detected; configure NEXO_MODEL_PATH when available'}")
    print(f"Telegram config: {'detected' if ENV_FILE.exists() else 'not configured'}")
    print(f"PM2: {detect_pm2() if is_termux() else 'desktop runtime managed separately'}")
    print(f"Setup state: {CONFIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
