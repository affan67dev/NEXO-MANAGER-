from __future__ import annotations

import os
from datetime import datetime

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except Exception:
    AsyncIOScheduler = None

class NexoScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler() if AsyncIOScheduler else None

    def start(self, callback=None):
        if not self.scheduler:
            return False
        if callback:
            hour = int(os.getenv("NEXO_BRIEFING_HOUR", "9"))
            minute = int(os.getenv("NEXO_BRIEFING_MINUTE", "0"))
            self.scheduler.add_job(callback, "cron", hour=hour, minute=minute, id="daily_briefing", replace_existing=True)
        if not self.scheduler.running:
            self.scheduler.start()
        return True

    def stop(self):
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)

scheduler = NexoScheduler()
