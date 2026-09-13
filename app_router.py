import json
import os
import re
import subprocess
import urllib.parse

APP_ALIASES = {
    "youtube": ["youtube", "yt"], "instagram": ["instagram", "insta"],
    "telegram": ["telegram", "tg"], "whatsapp": ["whatsapp", "wa"],
    "chrome": ["chrome", "google chrome"], "google": ["google"],
}

def detect_app(text):
    t = (text or "").lower()
    for app, aliases in APP_ALIASES.items():
        for alias in aliases:
            if re.search(r"\b" + re.escape(alias) + r"\b", t): return app
    return None

def detect_action(text):
    t = (text or "").lower()
    if any(x in t for x in ("play", "baja", "chala do", "song", "music")): return "play"
    if any(x in t for x in ("search", "find", "dhundh", "dhundho", "dhoondh", "dhoondo", "talash")): return "search"
    if any(x in t for x in ("open", "khol", "kholo", "launch", "start")): return "open"
    if any(x in t for x in ("close", "band", "exit")): return "close"
    return "unknown"

def extract_query(text, app):
    t = (text or "").strip()
    if app:
        for alias in APP_ALIASES[app]: t = re.sub(r"\b" + re.escape(alias) + r"\b", " ", t, flags=re.I)
    stop = ["search karo","search kar","search","find","play karo","play kar","play","baja do","baja","chala do","chala","dhundho","dhundh","dhoondo","dhoondh","talash","ki id","id do","par","mein","me","on","karo","kar","please","open","khol","kholo","song","music"]
    for word in sorted(stop, key=len, reverse=True): t = re.sub(r"\b" + re.escape(word) + r"\b", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()

def _open_url(url, message):
    try:
        p = subprocess.run(["termux-open-url", url], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=10, check=False)
        if p.returncode != 0: return False, p.stderr.strip() or "Couldn't open requested destination."
        return True, message
    except Exception as exc: return False, f"Couldn't open requested destination: {exc}"

def open_app(app):
    urls = {"youtube":"https://www.youtube.com/","instagram":"https://www.instagram.com/","telegram":"https://t.me/","whatsapp":"https://wa.me/","chrome":"https://www.google.com/","google":"https://www.google.com/"}
    if app not in urls: return False, f"I don't have an allowed launcher for {app} yet."
    return _open_url(urls[app], f"Opening {app}.")

def search_app(app, query):
    if not query: return False, "Tell me what you want me to search for."
    encoded = urllib.parse.quote_plus(query)
    urls = {"youtube":f"https://www.youtube.com/results?search_query={encoded}","google":f"https://www.google.com/search?q={encoded}","chrome":f"https://www.google.com/search?q={encoded}"}
    if app not in urls: return False, f"Search is not enabled for {app} yet."
    return _open_url(urls[app], f"Searching {app} for: {query}")

def play_media(app, query):
    if app != "youtube": return False, f"Media playback is not enabled for {app} yet."
    if not query: return False, "Tell me what you want me to play."
    return _open_url(f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}", f"Opening YouTube results for: {query}")

def window_control(primary_app, secondary_app=None, mode="split"):
    if mode not in {"split","pip","side_by_side"}: return False, "Unsupported window mode."
    command = os.getenv("NEXO_ANDROID_WINDOW_COMMAND", "").strip()
    if not command: return False, "Android window-control adapter is not configured for this device build."
    safe = set(APP_ALIASES)
    if primary_app not in safe or (secondary_app and secondary_app not in safe): return False, "Requested app is not allowlisted for window control."
    env = os.environ.copy(); env.update({"NEXO_PRIMARY_APP":primary_app,"NEXO_SECONDARY_APP":secondary_app or "","NEXO_WINDOW_MODE":mode})
    try:
        p = subprocess.run(["sh","-c",command], env=env, capture_output=True, text=True, timeout=20, check=False)
        if p.returncode != 0: return False, p.stderr.strip() or "Android window-control command failed."
        return True, "Android window-control command completed; OS-level layout verification is not available."
    except Exception as exc: return False, f"Android window-control failed: {exc}"

def parse_command(text):
    app = detect_app(text); action = detect_action(text)
    return {"app":app,"action":action,"query":extract_query(text,app) if action in {"search","play"} else ""}

def execute(text):
    command = parse_command(text)
    if not command["app"]: return {"ok":False,"verified":False,"message":"I couldn't identify the target app.","command":command}
    if command["action"] == "open": ok,message=open_app(command["app"])
    elif command["action"] == "search": ok,message=search_app(command["app"],command["query"])
    elif command["action"] == "play": ok,message=play_media(command["app"],command["query"])
    elif command["action"] == "close": ok,message=False,"Close control is not enabled yet."
    else: ok,message=False,"I understood the app, but not the requested action."
    return {"ok":ok,"verified":ok,"message":message,"command":command}

if __name__ == "__main__":
    import sys
    text=" ".join(sys.argv[1:]).strip()
    print(json.dumps(execute(text) if text else {"ok":False,"verified":False,"message":"No command supplied."}, indent=2, ensure_ascii=False))
