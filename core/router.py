from agents.manager.manager import NexoManager

_manager = NexoManager()

def route(text: str) -> str:
    return _manager.create_task(text).agent

def create_task(text: str):
    return _manager.create_task(text)
