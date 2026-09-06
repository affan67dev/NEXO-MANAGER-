class ManagerAgent:
    name="NEXO Manager"
    def route(self,task):
        t=task.lower()
        if any(x in t for x in ["research","search","market","competitor","latest"]):
            return "researcher"
        if any(x in t for x in ["code","bug","python","website","app","github"]):
            return "coder"
        if any(x in t for x in ["video","image","media","reel","thumbnail"]):
            return "media"
        return "llama"
