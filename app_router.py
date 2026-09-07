import re
import json
import subprocess
import urllib.parse

APP_ALIASES = {
    "youtube": ["youtube", "yt"],
    "instagram": ["instagram", "insta"],
    "telegram": ["telegram", "tg"],
    "chrome": ["chrome", "google chrome"],
    "google": ["google"],
}

def detect_app(text):
    t = text.lower()
    for app, aliases in APP_ALIASES.items():
        for alias in aliases:
            if re.search(r"\b" + re.escape(alias) + r"\b", t):
                return app
    return None

def detect_action(text):
    t = text.lower()

    if any(x in t for x in [
        "search", "find", "dhundh", "dhundho",
        "dhoondh", "dhoondo", "talash"
    ]):
        return "search"

    if any(x in t for x in [
        "open", "khol", "kholo", "launch", "start"
    ]):
        return "open"

    if any(x in t for x in [
        "close", "band", "band karo", "exit"
    ]):
        return "close"

    return "unknown"

def extract_query(text, app):
    t = text.strip()

    if app:
        for alias in APP_ALIASES[app]:
            t = re.sub(
                r"\b" + re.escape(alias) + r"\b",
                " ",
                t,
                flags=re.I
            )

    stop_words = [
        "search karo",
        "search kar",
        "search",
        "find",
        "dhundho",
        "dhundh",
        "dhoondo",
        "dhoondh",
        "talash",
        "ki id",
        "id do",
        "par",
        "mein",
        "me",
        "on",
        "karo",
        "kar",
        "please"
    ]

    for word in sorted(stop_words, key=len, reverse=True):
        t = re.sub(
            r"\b" + re.escape(word) + r"\b",
            " ",
            t,
            flags=re.I
        )

    t = re.sub(r"\s+", " ", t).strip()
    return t

def open_app(app):
    urls = {
        "youtube": "https://www.youtube.com/",
        "instagram": "https://www.instagram.com/",
        "telegram": "https://t.me/",
        "chrome": "https://www.google.com/",
        "google": "https://www.google.com/",
    }

    url = urls.get(app)

    if not url:
        return False, f"I don't have an allowed launcher for {app} yet."

    try:
        subprocess.run(
            ["termux-open-url", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False
        )
        return True, f"Opening {app}."
    except Exception:
        return False, f"Couldn't open {app}."

def search_app(app, query):
    if not query:
        return False, "Tell me what you want me to search for."

    encoded = urllib.parse.quote_plus(query)

    urls = {
        "youtube": f"https://www.youtube.com/results?search_query={encoded}",
        "google": f"https://www.google.com/search?q={encoded}",
        "chrome": f"https://www.google.com/search?q={encoded}",
    }

    if app == "instagram":
        return False, "Instagram search adapter is not enabled yet."

    if app not in urls:
        return False, f"Search is not enabled for {app} yet."

    try:
        subprocess.run(
            ["termux-open-url", urls[app]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False
        )
        return True, f"Searching {app} for: {query}"
    except Exception:
        return False, "Search action failed."

def parse_command(text):
    app = detect_app(text)
    action = detect_action(text)

    query = ""
    if action == "search":
        query = extract_query(text, app)

    return {
        "app": app,
        "action": action,
        "query": query
    }

def execute(text):
    command = parse_command(text)

    if not command["app"]:
        return {
            "ok": False,
            "message": "I couldn't identify the target app.",
            "command": command
        }

    if command["action"] == "open":
        ok, message = open_app(command["app"])

    elif command["action"] == "search":
        ok, message = search_app(
            command["app"],
            command["query"]
        )

    elif command["action"] == "close":
        ok = False
        message = "Close control is not enabled yet."

    else:
        ok = False
        message = "I understood the app, but not the requested action."

    return {
        "ok": ok,
        "message": message,
        "command": command
    }

if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]).strip()

    if not text:
        print(json.dumps({
            "ok": False,
            "message": "No command supplied."
        }, indent=2))
    else:
        print(
            json.dumps(
                execute(text),
                indent=2,
                ensure_ascii=False
            )
        )
