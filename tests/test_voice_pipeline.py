import unittest
from unittest.mock import patch
from voice_engine import NexoVoiceAssistant, VoiceState, is_wake_word, remove_wake_word

class FakePlanner:
    def __init__(self, tool_name="app_open", args=None):
        self.tool_name=tool_name; self.args=args or {"app":"youtube"}
    def run(self, goal, messages, tools, executor, owner, user_id=None, max_steps=6):
        outcome=executor(self.tool_name,self.args,owner=owner,user_id=user_id)
        return str(outcome.get("message","The requested action could not be completed."))

class VoicePipelineTests(unittest.TestCase):
    def test_alex_wake_variants(self):
        for text in ("Hey Alex","hey alex","Hey, Alex","HEY ALEX!","हे एलेक्स"):
            self.assertTrue(is_wake_word(text), text)
        self.assertFalse(is_wake_word("hello alex"))
        self.assertFalse(is_wake_word("alex is here"))
        self.assertEqual(remove_wake_word("Hey, Alex, open YouTube"), "open YouTube")

    def test_wake_does_not_execute_remainder(self):
        spoken=[]
        assistant=NexoVoiceAssistant(tts=lambda text: spoken.append(text) or True)
        result=assistant.process_text("Hey Alex, open YouTube")
        self.assertTrue(result.ok)
        self.assertEqual(result.stage,"wake")
        self.assertTrue(result.details["command_discarded"])
        self.assertEqual(spoken,["Yes, how can I help you?"])
        self.assertEqual(assistant.state,VoiceState.LISTENING)

    @patch("voice_engine.execute_registered_tool", return_value={"ok":True,"verified":True,"message":"Opening youtube."})
    def test_stt_manager_pipeline_and_tts(self,_tool):
        spoken=[]
        assistant=NexoVoiceAssistant(stt=lambda path: {"ok":True,"text":"open YouTube","provider":"test-stt"},
                                     tts=lambda text: spoken.append(text) or True)
        result=assistant.process_text("open YouTube",planner=FakePlanner())
        self.assertTrue(result.ok); self.assertTrue(result.verified)
        self.assertEqual(result.provider,"nexo-manager")
        self.assertEqual(spoken,["Opening youtube."])

    def test_stt_failure_is_not_fabricated(self):
        assistant=NexoVoiceAssistant(stt=lambda path: {"ok":False,"provider":"test","error":"permission denied"})
        result=assistant.listen_once()
        self.assertFalse(result.ok); self.assertEqual(result.stage,"stt")
        self.assertNotIn("understood",result.response.lower())

    def test_timeout_after_30_seconds(self):
        a=NexoVoiceAssistant(tts=lambda _: True,timeout_seconds=30)
        a.state=VoiceState.LISTENING; a.last_interaction=100.0
        self.assertTrue(a.timeout_check(130.0))
        self.assertEqual(a.state,VoiceState.IDLE)

    def test_timeout_resets_on_meaningful_interaction(self):
        a=NexoVoiceAssistant(tts=lambda _: True,timeout_seconds=30)
        a.state=VoiceState.LISTENING; a.last_interaction=100.0
        a.last_interaction=120.0
        self.assertFalse(a.timeout_check(140.0))
        self.assertTrue(a.timeout_check(151.0))

    def test_reactivation_after_timeout(self):
        spoken=[]
        a=NexoVoiceAssistant(tts=lambda text: spoken.append(text) or True,timeout_seconds=30)
        a.state=VoiceState.LISTENING; a.last_interaction=0.0
        self.assertTrue(a.timeout_check(30.0)); self.assertEqual(a.state,VoiceState.IDLE)
        r=a.process_text("Hey Alex")
        self.assertEqual(a.state,VoiceState.LISTENING); self.assertTrue(r.ok)

    def test_state_machine_values(self):
        self.assertEqual([s.value for s in VoiceState],["IDLE","WAKE_DETECTED","LISTENING","PROCESSING","SPEAKING"])

if __name__=="__main__":
    unittest.main()
