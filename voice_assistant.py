"""Legacy launcher retained for compatibility; ALEX is the user-facing voice identity."""
from __future__ import annotations
from voice_engine import NexoVoiceAssistant

def main() -> None:
    print("🤖 ALEX Voice Agent started")
    print("🎙️ Say: Hey Alex")
    NexoVoiceAssistant().run_forever()

if __name__ == "__main__":
    main()
