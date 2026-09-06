import re

SENSITIVE=re.compile(r"(password|otp|token|api[_ -]?key|secret|cvv|pin)",re.I)

def should_remember(text):
    if not text or SENSITIVE.search(text):
        return False
    keywords=("remember","my preference","i prefer","my project",
              "my goal","important","from now on")
    return any(k in text.lower() for k in keywords)

def category(text):
    t=text.lower()
    if "project" in t: return "project"
    if "goal" in t: return "goal"
    if "prefer" in t or "preference" in t: return "preference"
    return "important_fact"
