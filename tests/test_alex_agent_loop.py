import unittest
from core.alex_agent_loop import Decision, Risk, analyse, decide, understand


class AlexAgentLoopTests(unittest.TestCase):
    def test_understanding_extracts_android_target_and_outcome(self):
        u = understand("Hey Alex, open YouTube")
        self.assertEqual(u.target, "youtube")
        self.assertIn("android_app_control", u.required_capabilities)
        self.assertEqual(u.risk, Risk.LOW)

    def test_fix_request_becomes_multi_step(self):
        u = understand("Fix the OMNIX deployment and verify it")
        result = decide(analyse(u))
        self.assertEqual(result.decision, Decision.MULTI_STEP_TASK)

    def test_high_impact_request_requires_confirmation(self):
        u = understand("Send a WhatsApp message to Mother")
        result = decide(analyse(u))
        self.assertEqual(result.decision, Decision.CONFIRMATION)

    def test_read_only_request_is_inspection(self):
        u = understand("Check why OMNIX is failing")
        result = decide(analyse(u))
        self.assertEqual(result.decision, Decision.INSPECT)

    def test_normal_conversation_is_answer(self):
        u = understand("What is Python?")
        result = decide(analyse(u))
        self.assertEqual(result.decision, Decision.ANSWER)


if __name__ == "__main__":
    unittest.main()
