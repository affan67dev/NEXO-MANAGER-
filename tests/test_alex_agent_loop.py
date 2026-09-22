import unittest
from core.alex_agent_loop import Decision, Risk, analyse, decide, understand

class AlexAgentLoopTests(unittest.TestCase):
    def test_understanding_extracts_android_target(self):
        u=understand("Hey Alex, open YouTube")
        self.assertEqual(u.target,"youtube")
        self.assertIn("android_app_control",u.required_capabilities)
        self.assertEqual(u.risk,Risk.LOW)

    def test_fix_request_becomes_multi_step(self):
        u=understand("Fix the OMNIX deployment and verify it")
        self.assertEqual(decide(analyse(u)).decision,Decision.MULTI_STEP_TASK)

    def test_high_impact_request_requires_confirmation(self):
        u=understand("Send a WhatsApp message")
        self.assertEqual(decide(analyse(u)).decision,Decision.CONFIRMATION)

    def test_read_only_request_is_inspection(self):
        u=understand("Check why OMNIX is failing")
        self.assertEqual(decide(analyse(u)).decision,Decision.INSPECT)

    def test_normal_conversation_is_answer(self):
        u=understand("What is Python?")
        self.assertEqual(decide(analyse(u)).decision,Decision.ANSWER)

if __name__=="__main__":
    unittest.main()
