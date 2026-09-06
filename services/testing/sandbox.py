from __future__ import annotations
import subprocess
from pathlib import Path

def run_tests(test_path: str = "tests") -> dict:
    root = Path(__file__).resolve().parents[2]
    target = root / test_path
    if not target.exists():
        return {"status":"NOT_RUN","reason":"test_path_missing","path":str(target)}
    result = subprocess.run(
        ["python","-m","pytest","-q",str(target)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300
    )
    return {
        "status":"PASS" if result.returncode == 0 else "FAIL",
        "return_code":result.returncode,
        "stdout":result.stdout[-5000:],
        "stderr":result.stderr[-5000:]
    }
