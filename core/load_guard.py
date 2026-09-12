from __future__ import annotations

import asyncio
import time
from collections import deque

# Conservative defaults for a low-RAM Android/Termux deployment.
PER_USER_INTERVAL = 1.0       # 1 accepted request/user/second
MAX_ACTIVE = 1                # one local Llama inference at a time
MAX_QUEUE = 4                 # bounded waiting work; never grow without limit
MAX_WAIT_SECONDS = 20.0       # queued requests fail fast instead of waiting forever


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
            self._queued += 1

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.max_wait)
        except asyncio.TimeoutError:
            async with self._lock:
                self._queued = max(0, self._queued - 1)
            return False, "queue_timeout"

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
