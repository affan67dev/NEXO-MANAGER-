"""Legacy launcher retained for compatibility; ALEX is the user-facing voice identity."""
from __future__ import annotations
import argparse
import signal
import time
from voice_engine import NexoVoiceAssistant

def main() -> None:
    parser = argparse.ArgumentParser(description="ALEX voice runtime")
    parser.add_argument("--wake-once", action="store_true", help="perform one explicit wake recognition")
    args = parser.parse_args()
    assistant = NexoVoiceAssistant()
    wake_requested = {"value": args.wake_once}

    def request_wake(_signum, _frame):
        wake_requested["value"] = True

    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, request_wake)

    print("🤖 ALEX Voice Agent started")
    print("🎙️ IDLE: no microphone polling; use the configured wake trigger")
    while True:
        try:
            if wake_requested["value"] and assistant.state.value == "IDLE":
                wake_requested["value"] = False
                result = assistant.wake_once()
                print(result.as_dict(), flush=True)
                if result.ok and assistant.state.value != "IDLE":
                    assistant.run_active_session()
            else:
                time.sleep(1.0)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            assistant.state = assistant.state.IDLE
            print(f"ALEX runtime error: {type(exc).__name__}", flush=True)
            time.sleep(1.0)

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
