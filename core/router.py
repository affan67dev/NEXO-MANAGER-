from tools.tool_registry import available_tools

def classify_request(text):
    t=text.lower()
    if any(x in t for x in ["search web","search online","latest news","current information","google search","internet"]):
        return "web_search"
    if any(x in t for x in ["remind me","reminder","schedule","alarm","tomorrow","every day","every week"]):
        return "automation"
    if any(x in t for x in ["remember this","save this","my preference","my project","my goal"]):
        return "memory"
    if any(x in t for x in ["code","python","program","bug","error","script"]):
        return "coding"
    return "chat"

def route(text):
    intent=classify_request(text)
    return {"intent":intent,"available_tools":list(available_tools().keys())}
