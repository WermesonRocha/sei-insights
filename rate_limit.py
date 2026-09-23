import logging
import random
import time

logger = logging.getLogger("sei-insights")


class RateLimiter:
    def __init__(self, min_delay: float, max_delay: float):
        if min_delay < 0:
            raise ValueError("min_delay must be non-negative")
        if max_delay < min_delay:
            raise ValueError("max_delay must be >= min_delay")
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._last_request = 0.0

    def wait(self) -> None:
        target = random.uniform(self.min_delay, self.max_delay)
        now = time.monotonic()
        elapsed = now - self._last_request
        remaining = target - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request = time.monotonic()

    def wait_seconds(self, seconds: float) -> None:
        time.sleep(seconds)
        self._last_request = time.monotonic()
