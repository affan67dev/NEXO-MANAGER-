from __future__ import annotations
from dataclasses import dataclass

@dataclass
class VoiceResult:
    text: str
    confidence: float | None = None

class VoiceAdapter:
    """Provider-neutral STT/TTS interface. No microphone or speaker access by default."""

    def transcribe_result(self, text: str, confidence: float | None = None) -> VoiceResult:
        return VoiceResult(text=text, confidence=confidence)

    def prepare_speech(self, text: str) -> dict[str, str]:
        return {
            "text": text,
            "status": "READY_FOR_TTS_PROVIDER",
            "note": "Connect an authorized TTS provider before playback."
        }
