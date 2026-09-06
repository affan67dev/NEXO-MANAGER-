TOOLS={
    "web_search":{"enabled":True,"module":"tools.web_search","function":"search_web"},
    "memory":{"enabled":True,"module":"core.memory_engine"},
    "automation":{"enabled":True,"module":"automation.scheduler"},
    "android":{"enabled":False,"reason":"Requires explicit controlled integration"},
    "voice_stt":{"enabled":False,"reason":"Voice layer not installed yet"},
    "voice_tts":{"enabled":False,"reason":"Voice layer not installed yet"}
}

def available_tools():
    return {k:v for k,v in TOOLS.items() if v.get("enabled")}
