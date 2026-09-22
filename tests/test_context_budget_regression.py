from __future__ import annotations

import unittest

from services.context_budget import fit_messages, input_budget
import telegram_llama


class ContextBudgetRegressionTests(unittest.TestCase):
    def test_simple_request_survives_accumulated_history(self):
        old = [("user", "old user turn " * 40), ("assistant", "old assistant turn " * 40)] * 8
        messages = telegram_llama.build_llm_messages("Who are you", old, "", "")
        fitted = fit_messages(messages, [])
        self.assertEqual(fitted[-1], {"role": "user", "content": "Who are you"})
        self.assertEqual(fitted[0]["role"], "system")
        self.assertLessEqual(len(fitted), 1 + 8 + 1)

    def test_current_user_is_mandatory_while_optional_context_is_droppable(self):
        messages = [
            {"role": "system", "content": "core policy"},
            {"role": "system", "content": "optional memory " * 500},
            {"role": "assistant", "content": "optional history " * 500},
            {"role": "user", "content": "What is 2 + 2?"},
        ]
        fitted = fit_messages(messages, [], budget=max(128, input_budget()))
        self.assertEqual(fitted[0]["content"], "core policy")
        self.assertEqual(fitted[-1]["content"], "What is 2 + 2?")
        self.assertNotIn("optional history " * 2, "\n".join(m["content"] for m in fitted[1:-1]))

    def test_individual_history_turns_are_bounded_before_provider(self):
        messages = telegram_llama.build_llm_messages(
            "Hello",
            [("assistant", "x" * 10000)] * 20,
            "",
            "",
            include_history=True,
        )
        history = [m for m in messages if m["role"] == "assistant"]
        self.assertTrue(history)
        self.assertTrue(all(len(m["content"]) <= telegram_llama.MAX_TURN_CHARS for m in history))

if __name__ == "__main__":
    unittest.main()
