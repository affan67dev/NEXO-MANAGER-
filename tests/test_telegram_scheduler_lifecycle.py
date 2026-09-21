from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from services.scheduler import NexoScheduler


class SchedulerLifecycleTests(unittest.TestCase):
    def test_scheduler_requires_a_running_loop(self):
        runtime = NexoScheduler()
        if runtime.scheduler is None:
            self.skipTest("APScheduler is unavailable")
        with self.assertRaises(RuntimeError):
            runtime.start()

    def test_scheduler_starts_and_stops_inside_running_loop(self):
        runtime = NexoScheduler()
        if runtime.scheduler is None:
            self.skipTest("APScheduler is unavailable")

        async def exercise():
            self.assertTrue(runtime.start(lambda: None, lambda: None))
            self.assertTrue(runtime.scheduler.running)
            self.assertIsNotNone(runtime.scheduler.get_job("daily_briefing"))
            self.assertIsNotNone(runtime.scheduler.get_job("daily_maintenance"))
            runtime.stop()
            self.assertFalse(runtime.scheduler.running)

        asyncio.run(exercise())


class TelegramStartupLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_init_starts_and_post_shutdown_stops_scheduler(self):
        import telegram_llama

        with patch.object(telegram_llama.scheduler, "start") as start, patch.object(
            telegram_llama.scheduler, "stop"
        ) as stop:
            await telegram_llama._post_init(MagicMock())
            start.assert_called_once_with(
                telegram_llama.daily_briefing, telegram_llama.daily_maintenance
            )
            await telegram_llama._post_shutdown(MagicMock())
            stop.assert_called_once_with()

    def test_telegram_optional_context_is_separate_from_core_system_prompt(self):
        import telegram_llama

        with patch.object(telegram_llama, "SYSTEM", "CORE"):
            messages = telegram_llama.build_llm_messages(
                "What is 2+2?",
                [("assistant", "old answer")],
                "memory",
                "knowledge",
            )
        self.assertEqual(messages[0], {"role": "system", "content": "CORE"})
        self.assertEqual(messages[1]["role"], "system")
        self.assertIn("memory", messages[1]["content"])
        self.assertIn("knowledge", messages[2]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "What is 2+2?"})

    def test_telegram_builder_keeps_scheduler_lifecycle_hooks(self):
        import telegram_llama

        self.assertTrue(callable(telegram_llama._post_init))
        self.assertTrue(callable(telegram_llama._post_shutdown))

    def test_main_wires_scheduler_to_application_lifecycle(self):
        import telegram_llama

        fake_app = MagicMock()
        fake_builder = MagicMock()
        for method in ("token", "concurrent_updates", "update_queue", "post_init", "post_shutdown"):
            getattr(fake_builder, method).return_value = fake_builder
        fake_builder.build.return_value = fake_app

        with patch.object(telegram_llama, "TOKEN", "test-token"), patch.object(
            telegram_llama.Application, "builder", return_value=fake_builder
        ), patch.object(telegram_llama.scheduler, "start") as start, patch.object(
            telegram_llama.scheduler, "stop"
        ) as stop:
            telegram_llama.main()

        fake_builder.post_init.assert_called_once_with(telegram_llama._post_init)
        fake_builder.post_shutdown.assert_called_once_with(telegram_llama._post_shutdown)
        fake_app.run_polling.assert_called_once_with(drop_pending_updates=True)
        start.assert_not_called()
        stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
