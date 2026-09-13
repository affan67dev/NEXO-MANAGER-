import tempfile
import unittest
from pathlib import Path

from voice_engine import NexoVoiceAssistant, VoiceResult, is_wake_word, remove_wake_word


class VoicePipelineTests(unittest.TestCase):
    def test_wake_word_detection(self):
        self.assertTrue(is_wake_word("Hey Nexo"))
        self.assertTrue(is_wake_word("हे नेक्सो"))
        self.assertFalse(is_wake_word("hello assistant"))
        self.assertEqual(remove_wake_word("Hey Nexo, open YouTube"), "open YouTube")

    def test_wake_only_speaks_confirmation(self):
        spoken = []
        assistant = NexoVoiceAssistant(tts=lambda text: spoken.append(text) or True,
                                       tool_executor=lambda text, confirmation: {"ok": False})
        result = assistant.process_text("Hey Nexo")
        self.assertTrue(result.ok)
        self.assertEqual(result.response, "Yes, how can I help you?")
        self.assertEqual(spoken, ["Yes, how can I help you?"])

    def test_pipeline_routes_through_nexo_and_executes_tool_then_tts(self):
        spoken = []
        executed = []

        def tool(text, confirmation):
            executed.append((text, confirmation))
            return {"ok": True, "verified": True, "message": "Opening youtube."}

        assistant = NexoVoiceAssistant(tts=lambda text: spoken.append(text) or True,
                                       tool_executor=tool)
        result = assistant.process_text("Hey Nexo, open YouTube")

        self.assertTrue(result.ok)
        self.assertTrue(result.verified)
        self.assertEqual(result.text, "open YouTube")
        self.assertEqual(result.details["agent"], "planning")
        self.assertEqual(executed, [("open YouTube", False)])
        self.assertEqual(spoken, ["Opening youtube."])

    def test_stt_injection_connects_audio_to_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "input.wav"
            audio.write_bytes(b"RIFF" + b"0" * 100)
            spoken = []
            assistant = NexoVoiceAssistant(
                stt=lambda path: {"ok": True, "text": "Hey Nexo, open YouTube", "provider": "test-stt"},
                recorder=lambda seconds: audio,
                tts=lambda text: spoken.append(text) or True,
                tool_executor=lambda text, confirmation: {"ok": True, "verified": True, "message": "Opening youtube."},
            )
            result = assistant.listen_once(1)
            self.assertTrue(result.ok)
            self.assertEqual(result.provider, "nexo-manager")
            self.assertEqual(result.text, "open YouTube")
            self.assertEqual(spoken, ["Opening youtube."])

    def test_sensitive_action_requires_confirmation(self):
        spoken = []
        assistant = NexoVoiceAssistant(tts=lambda text: spoken.append(text) or True)
        result = assistant.process_text("Hey Nexo, delete everything")
        self.assertTrue(result.ok)
        self.assertFalse(result.verified)
        self.assertTrue(result.details["tool"]["requires_confirmation"])
        self.assertEqual(spoken, ["I need your confirmation before I do that."])


if __name__ == "__main__":
    unittest.main()
