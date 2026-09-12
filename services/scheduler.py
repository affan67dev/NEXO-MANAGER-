from __future__ import annotations

import os

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except Exception:
    AsyncIOScheduler = None


class NexoScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler() if AsyncIOScheduler else None

    def start(self, briefing_callback=None, maintenance_callback=None):
        if not self.scheduler:
            return False
        if briefing_callback:
            hour = int(os.getenv("NEXO_BRIEFING_HOUR", "9"))
            minute = int(os.getenv("NEXO_BRIEFING_MINUTE", "0"))
            self.scheduler.add_job(briefing_callback, "cron", hour=hour, minute=minute, id="daily_briefing", replace_existing=True, coalesce=True, max_instances=1)
        if maintenance_callback:
            hour = int(os.getenv("NEXO_MAINTENANCE_HOUR", "3"))
            minute = int(os.getenv("NEXO_MAINTENANCE_MINUTE", "0"))
            self.scheduler.add_job(maintenance_callback, "cron", hour=hour, minute=minute, id="daily_maintenance", replace_existing=True, coalesce=True, max_instances=1)
        if not self.scheduler.running:
            self.scheduler.start()
        return True

    def stop(self):
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)


scheduler = NexoScheduler()
