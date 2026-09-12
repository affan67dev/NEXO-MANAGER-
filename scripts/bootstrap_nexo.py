#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, platform, shutil, sqlite3, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".nexo" / "setup"
CONFIG = STATE / "runtime.json"
VENV = REPO / ".venv"
ENV_FILE = Path.home() / ".nexo.env"
DB = REPO / "data" / "memory.db"
PM2_NAMES = ("nexo-backend", "nexo-llama")

def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, check=check)

def hardware() -> dict[str, object]:
    info = {"os": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version(), "cpu_count": os.cpu_count() or 1, "ram_bytes": None, "gpu": []}
    try:
        import psutil
        info["ram_bytes"] = int(psutil.virtual_memory().total)
    except Exception:
        pass
    probes = []
    if shutil.which("nvidia-smi"): probes.append(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    if shutil.which("rocm-smi"): probes.append(["rocm-smi", "--showproductname"])
    if platform.system() == "Darwin" and shutil.which("system_profiler"): probes.append(["system_profiler", "SPDisplaysDataType"])
    if platform.system() == "Windows" and shutil.which("powershell"): probes.append(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"])
    for cmd in probes:
        r = run(cmd)
        if r.returncode == 0: info["gpu"] += [x.strip() for x in r.stdout.splitlines() if x.strip()]
    info["gpu"] = info["gpu"][:8]
    return info

def find_llama() -> str | None:
    candidates = [os.getenv("LLAMA_SERVER", ""), shutil.which("llama-server") or "", str(Path.home()/"llama.cpp"/"build"/"bin"/"llama-server"), str(Path.home()/"llama.cpp"/"llama-server"), str(REPO/"llama.cpp"/"build"/"bin"/"llama-server")]
    for item in candidates:
        p = Path(item).expanduser() if item else None
        if p and p.is_file() and os.access(p, os.X_OK): return str(p.resolve())
    return None

def find_model() -> str | None:
    configured = os.getenv("NEXO_MODEL_PATH", "").strip()
    if configured and Path(configured).expanduser().is_file(): return str(Path(configured).expanduser().resolve())
    roots = [REPO/"models", Path.home()/"models"]
    if os.getenv("PREFIX"): roots.append(Path("/sdcard/Download"))
    for root in roots:
        if root.is_dir():
            found = next(root.glob("*.gguf"), None)
            if found: return str(found.resolve())
    return None

def init_sqlite() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn: conn.execute("PRAGMA journal_mode=WAL")

def ensure_venv() -> Path:
    if not (VENV/"pyvenv.cfg").exists(): subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    return VENV/("Scripts/python.exe" if os.name == "nt" else "bin/python")

def install_dependencies(py: Path) -> None:
    manifest = REPO/"requirements-nexo.txt"
    if not manifest.is_file(): raise RuntimeError("requirements-nexo.txt is missing")
    subprocess.run([str(py), "-m", "pip", "install", "-r", str(manifest)], check=True)

def detect_pm2() -> dict[str, object]:
    pm2 = shutil.which("pm2")
    result: dict[str, object] = {"available": bool(pm2), "processes": {}}
    if not pm2: return result
    for name in PM2_NAMES: result["processes"][name] = run([pm2, "describe", name]).returncode == 0
    return result

def wizard() -> str:
    if not sys.stdin.isatty(): return "personal"
    value = input("NEXO profile [personal/shared] (personal): ").strip().lower() or "personal"
    return value if value in {"personal", "shared"} else "personal"

def desktop_shortcut() -> bool:
    if platform.system() != "Linux": return False
    desktop = Path(os.getenv("XDG_DESKTOP_DIR", str(Path.home()/"Desktop")))
    if not desktop.is_dir(): return False
    target = desktop/"NEXO.desktop"
    target.write_text("[Desktop Entry]\nType=Application\nName=NEXO\nTerminal=true\nExec=" + str(REPO/"bootstrap.sh") + "\nPath=" + str(REPO) + "\n", encoding="utf-8")
    target.chmod(0o755)
    return True

def main() -> int:
    p = argparse.ArgumentParser(description="Idempotent NEXO one-click bootstrap")
    p.add_argument("--no-install", action="store_true")
    p.add_argument("--wizard", action="store_true")
    p.add_argument("--desktop-shortcut", action="store_true")
    args = p.parse_args()
    if not (REPO/".git").exists(): print("ERROR: run from a NEXO checkout", file=sys.stderr); return 2
    hw, llama, model = hardware(), find_llama(), find_model()
    init_sqlite()
    py = ensure_venv()
    if not args.no_install: install_dependencies(py)
    profile = wizard() if args.wizard else "personal"
    shortcut = desktop_shortcut() if args.desktop_shortcut else False
    data = {"schema_version": 1, "repo": str(REPO), "hardware": hw, "python": {"executable": str(py), "venv": str(VENV)}, "llama_server": llama, "model": model, "telegram_env_file": str(ENV_FILE) if ENV_FILE.exists() else None, "pm2": detect_pm2(), "profile": profile, "desktop_shortcut": shortcut}
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp"); tmp.write_text(json.dumps(data, indent=2, sort_keys=True)+"\n", encoding="utf-8"); os.replace(tmp, CONFIG)
    print("NEXO bootstrap: PASS")
    print(f"Platform: {hw['os']} / {hw['machine']}")
    print(f"Python environment: {py}")
    print(f"SQLite: {DB}")
    print(f"llama-server: {llama or 'not detected; existing install preserved'}")
    print(f"GGUF model: {model or 'not detected; configure NEXO_MODEL_PATH when available'}")
    print(f"Telegram config: {'detected' if ENV_FILE.exists() else 'not configured'}")
    print(f"PM2: {detect_pm2()}")
    print(f"Setup state: {CONFIG}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
