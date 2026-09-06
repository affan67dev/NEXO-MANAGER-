import re

SPAM=[
"free money","click here","winner","urgent prize",
"claim your reward","crypto giveaway"
]

def inspect(text):
    t=text.lower().strip()
    if not t:
        return {"allow":False,"reason":"empty"}
    hits=[x for x in SPAM if x in t]
    if hits:
        return {"allow":False,"reason":"possible_spam","matches":hits}
    if len(t)>10000:
        return {"allow":False,"reason":"message_too_large"}
    return {"allow":True,"reason":"accepted"}
