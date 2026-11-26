"""A small fixed-window limiter for the routes worth protecting."""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request

from app.core.errors import APIError

_HITS: dict[str, list[float]] = defaultdict(list)


class RateLimiter:
    """``Depends(RateLimiter(times=10, seconds=60, scope="login"))``."""

    def __init__(self, times: int, seconds: int, scope: str = "default") -> None:
        self.times = times
        self.seconds = seconds
        self.scope = scope

    async def __call__(self, request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        self.check(f"{self.scope}:{client}")

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = [stamp for stamp in _HITS[key] if stamp > now - self.seconds]
        if len(hits) >= self.times:
            retry_after = max(1, int(self.seconds - (now - hits[0])))
            _HITS[key] = hits
            raise APIError(
                "rate_limit_exceeded",
                f"Too many requests. Try again in {retry_after}s.",
                429,
                {"Retry-After": str(retry_after)},
            )
        hits.append(now)
        _HITS[key] = hits


def reset_rate_limits() -> None:
    """Used by the test suite; never called at runtime."""
    _HITS.clear()
