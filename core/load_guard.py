from __future__ import annotations

import asyncio
import time

PER_USER_INTERVAL = 1.0
MAX_ACTIVE = 1
MAX_QUEUE = 4
MAX_WAIT_SECONDS = 20.0
MAX_TRACKED_USERS = 1024


class LoadGuard:
    def __init__(
        self,
        per_user_interval: float = PER_USER_INTERVAL,
        max_active: int = MAX_ACTIVE,
        max_queue: int = MAX_QUEUE,
        max_wait: float = MAX_WAIT_SECONDS,
    ) -> None:
        self.per_user_interval = max(0.1, float(per_user_interval))
        self.max_active = max(1, int(max_active))
        self.max_queue = max(0, int(max_queue))
        self.max_wait = max(0.1, float(max_wait))
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(self.max_active)
        self._last_request: dict[int, float] = {}
        self._queued = 0
        self._active = 0

    async def acquire(self, user_id: int) -> tuple[bool, str]:
        now = time.monotonic()
        async with self._lock:
            last = self._last_request.get(user_id)
            if last is not None and now - last < self.per_user_interval:
                return False, "rate_limited"

            if self._active + self._queued >= self.max_active + self.max_queue:
                return False, "overloaded"

            self._last_request[user_id] = now
            if len(self._last_request) > MAX_TRACKED_USERS:
                stale = sorted(self._last_request.items(), key=lambda item: item[1])
                for uid, _stamp in stale[:MAX_TRACKED_USERS // 2]:
                    self._last_request.pop(uid, None)
            self._queued += 1

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.max_wait)
        except asyncio.TimeoutError:
            async with self._lock:
                self._queued = max(0, self._queued - 1)
            return False, "queue_timeout"
        except asyncio.CancelledError:
            async with self._lock:
                self._queued = max(0, self._queued - 1)
            raise

        async with self._lock:
            self._queued = max(0, self._queued - 1)
            self._active += 1
        return True, "accepted"

    async def release(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)
        self._semaphore.release()

    async def snapshot(self) -> dict[str, int | float]:
        async with self._lock:
            return {
                "active": self._active,
                "queued": self._queued,
                "max_active": self.max_active,
                "max_queue": self.max_queue,
                "per_user_interval_seconds": self.per_user_interval,
            }


load_guard = LoadGuard()
