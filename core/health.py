from __future__ import annotations

import urllib.request

URL = "http://127.0.0.1:8080/health"


def check_llama() -> dict[str, object]:
    try:
        with urllib.request.urlopen(URL, timeout=5) as response:
            return {"ok": True, "status": response.status}
    except Exception:
        return {"ok": False, "status": None}


if __name__ == "__main__":
    print(check_llama())
