from __future__ import annotations

import unittest
from unittest.mock import patch


class TelegramSchedulerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_starts_once_and_stops_during_application_lifecycle(self):
        import telegram_llama

        telegram_llama._scheduler_started = False
        with patch.object(telegram_llama.scheduler, "start") as start, patch.object(telegram_llama.scheduler, "stop") as stop:
            await telegram_llama._post_init(None)
            await telegram_llama._post_init(None)
            self.assertEqual(start.call_count, 1)
            start.assert_called_once_with(telegram_llama.daily_briefing, telegram_llama.daily_maintenance)

            await telegram_llama._post_shutdown(None)
            stop.assert_called_once_with()

        telegram_llama._scheduler_started = False


if __name__ == "__main__":
    unittest.main()
