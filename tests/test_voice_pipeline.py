import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voice_engine import NexoVoiceAssistant, execute_via_nexo, is_wake_word, remove_wake_word


class FakePlanner:
    def __init__(self, tool_name="app_open", args=None):
        self.tool_name = tool_name
        self.args = args or {"app": "youtube"}

    def run(self, goal, messages, tools, executor, owner, user_id=None, max_steps=6):
        outcome = executor(self.tool_name, self.args, owner=owner, user_id=user_id)
        return str(outcome.get("message", "The requested action could not be completed."))


class VoicePipelineTests(unittest.TestCase):
    def test_wake_word_detection(self):
        self.assertTrue(is_wake_word("Hey Nexo"))
        self.assertTrue(is_wake_word("हे नेक्सो"))
        self.assertFalse(is_wake_word("hello assistant"))
        self.assertEqual(remove_wake_word("Hey Nexo, open YouTube"), "open YouTube")

    def test_wake_only_speaks_confirmation(self):
        spoken = []
        assistant = NexoVoiceAssistant(tts=lambda text: spoken.append(text) or True)
        result = assistant.process_text("Hey Nexo")
        self.assertTrue(result.ok)
        self.assertTrue(result.verified)
        self.assertEqual(result.response, "Yes, how can I help you?")
        self.assertEqual(spoken, ["Yes, how can I help you?"])

    @patch("voice_engine.execute_registered_tool", return_value={"ok": True, "verified": True, "message": "Opening youtube."})
    def test_llama_planner_selects_tool_and_result_is_verified(self, _tool):
        outcome = execute_via_nexo("open YouTube", planner=FakePlanner())
        self.assertTrue(outcome["ok"])
        self.assertTrue(outcome["verified"])
        self.assertEqual(outcome["tools"][0]["name"], "app_open")

    @patch("voice_engine.execute_registered_tool", return_value={"ok": True, "verified": True, "message": "Opening youtube."})
    def test_audio_stt_connects_to_nexo_and_tts(self, _tool):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "input.wav"
            audio.write_bytes(b"RIFF" + b"0" * 100)
            spoken = []
            assistant = NexoVoiceAssistant(
                stt=lambda path: {"ok": True, "text": "Hey Nexo, open YouTube", "provider": "test-stt"},
                recorder=lambda seconds: audio,
                tts=lambda text: spoken.append(text) or True,
            )
            stt = assistant.stt(audio)
            result = assistant.process_text(stt["text"], planner=FakePlanner())
            self.assertTrue(result.ok)
            self.assertTrue(result.verified)
            self.assertEqual(result.text, "open YouTube")
            self.assertEqual(spoken, ["Opening youtube."])

    def test_sensitive_action_requires_explicit_confirmation(self):
        spoken = []
        planner = FakePlanner("device_action", {"action": "shutdown"})
        result = NexoVoiceAssistant(tts=lambda text: spoken.append(text) or True).process_text("Hey Nexo, shutdown the device", planner=planner)
        self.assertFalse(result.details["verified"])
        self.assertTrue(result.details["requires_confirmation"])
        self.assertEqual(spoken, ["I need your explicit confirmation before I do that."])

    @patch("voice_engine.execute_registered_tool", return_value={"ok": False, "verified": False, "message": "failed"})
    def test_tool_failure_is_not_reported_as_verified(self, _tool):
        planner = FakePlanner()
        result = execute_via_nexo("open YouTube", planner=planner)
        self.assertFalse(result["verified"])


if __name__ == "__main__":
    unittest.main()
