"""A fixed-window request counter for the public routes."""

import math
import threading
import time
from collections.abc import Callable

# Keys kept before expired entries are dropped on the next check.
MAX_KEYS = 10_000


class TokenLimiter:
    """At most `limit` checks per `window` seconds for each key, counted
    in this process. ponytail: per-process state, so N workers allow N
    times the limit; Redis or an edge limiter (PRD) if that matters."""

    def __init__(
        self,
        limit: int,
        window: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit, self.window, self.clock = limit, window, clock
        self._seen: dict[str, tuple[int, int]] = {}
        self._swept = -1
        self._lock = threading.Lock()

    def check(self, key: str) -> int | None:
        """None when the key is under its limit (this call counts);
        otherwise the whole seconds until its window ends, at least 1."""
        now = self.clock()
        index = int(now // self.window)
        with self._lock:
            if len(self._seen) > MAX_KEYS and self._swept != index:
                # A soft cap, swept at most once per window: keys seen in
                # this window stay until the next.
                self._seen = {
                    k: v for k, v in self._seen.items() if v[0] == index
                }
                self._swept = index
            start, count = self._seen.get(key, (index, 0))
            if start != index:
                count = 0
            if count >= self.limit:
                # now is inside the window, so this is at least 1.
                return math.ceil((index + 1) * self.window - now)
            self._seen[key] = (index, count + 1)
            return None
