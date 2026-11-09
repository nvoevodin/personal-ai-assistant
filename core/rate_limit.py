"""In-memory rate limiter using sliding window log algorithm."""

import asyncio
import time
from collections import defaultdict
from core.errors import RateLimitExceededError


class RateLimiter:
    """Sliding-window rate limiter for tracking and throttling actions per user."""

    def __init__(self, max_calls: int = 30, window_seconds: float = 60.0) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._history: dict[int, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: int) -> bool:
        """Attempt to acquire a rate limit slot. Raises RateLimitExceededError if throttled."""
        now = time.monotonic()
        threshold = now - self.window_seconds

        async with self._lock:
            # Filter timestamps outside the sliding window
            timestamps = [ts for ts in self._history[user_id] if ts > threshold]
            if len(timestamps) >= self.max_calls:
                oldest = timestamps[0]
                retry_after = max(1.0, (oldest + self.window_seconds) - now)
                raise RateLimitExceededError(
                    message=f"Rate limit exceeded. Allowed {self.max_calls} requests per {int(self.window_seconds)}s.",
                    retry_after=retry_after,
                )

            timestamps.append(now)
            self._history[user_id] = timestamps
            return True

    async def reset(self, user_id: int | None = None) -> None:
        """Reset history for a specific user or all users."""
        async with self._lock:
            if user_id is not None:
                self._history.pop(user_id, None)
            else:
                self._history.clear()
