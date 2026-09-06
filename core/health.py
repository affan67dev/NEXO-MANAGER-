import urllib.request

URL = "http://127.0.0.1:8080/health"

try:
    with urllib.request.urlopen(URL, timeout=5) as r:
        print("✅ Llama server:", r.read().decode())
except Exception as e:
    print("❌ Llama server unavailable:", e)
