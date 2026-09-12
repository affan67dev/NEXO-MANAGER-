from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_TEST_OUTPUT = 5000


def run_tests(test_path: str = "tests") -> dict:
    try:
        raw = Path(test_path).expanduser()
        target = (ROOT / raw).resolve() if not raw.is_absolute() else raw.resolve()
        if target != ROOT and ROOT not in target.parents:
            return {"status": "NOT_RUN", "reason": "test_path_not_allowed"}
    except (OSError, RuntimeError):
        return {"status": "NOT_RUN", "reason": "invalid_test_path"}

    if not target.exists():
        return {"status": "NOT_RUN", "reason": "test_path_missing", "path": str(target)}
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "-q", str(target)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "FAIL", "reason": "test_execution_failed"}
    return {
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "return_code": result.returncode,
        "stdout": result.stdout[-MAX_TEST_OUTPUT:],
        "stderr": result.stderr[-MAX_TEST_OUTPUT:],
    }
