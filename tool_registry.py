import json
import app_router

SAFE_TOOLS = {
    "app_open": True,
    "app_search": True,
    "web_search": True,
    "url_open": True,
    "file_read": True,
    "battery_status": True,
    "wifi_control": True,
}

BLOCKED_FILE_EXTENSIONS = {
    ".env", ".db", ".sqlite", ".sqlite3",
    ".pem", ".key", ".p12"
}

def list_tools():
    return list(SAFE_TOOLS.keys())

def run_app_command(text):
    return app_router.execute(text)

def can_read_file(path):
    p = path.lower()
    return not any(p.endswith(x) for x in BLOCKED_FILE_EXTENSIONS)

def tool_status():
    return {
        "ok": True,
        "tools": SAFE_TOOLS,
        "blocked_file_types": sorted(BLOCKED_FILE_EXTENSIONS)
    }

if __name__ == "__main__":
    print(json.dumps(tool_status(), indent=2))
