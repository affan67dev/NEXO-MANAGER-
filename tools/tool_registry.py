TOOLS={
    "web_search":{"enabled":True,"module":"tools.web_search","function":"search_web"},
    "memory":{"enabled":True,"module":"core.memory_engine"},
    "automation":{"enabled":True,"module":"automation.scheduler"},
    "android":{"enabled":True,"reason":"Controlled Android tools are registered in nexo_tools"},
    "voice_stt":{"enabled":True,"module":"voice_engine","function":"speech_to_text"},
    "voice_tts":{"enabled":True,"module":"voice_engine","function":"speak"}
}

def available_tools():
    return {k:v for k,v in TOOLS.items() if v.get("enabled")}
