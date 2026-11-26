"""One HTTP client for the whole process.

Creating an ``AsyncClient`` per check would throw away connection reuse and
re-do TLS on every probe — for a service whose entire job is making the same
requests over and over, that is the difference between a 40 ms check and a
200 ms one. The client is opened at startup and closed at shutdown.
"""

from __future__ import annotations

import httpx

from app.core.config import settings

# Generous enough for the scheduler's concurrency, bounded so a burst cannot
# exhaust file descriptors.
LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=40, keepalive_expiry=30.0)

_client: httpx.AsyncClient | None = None
_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Install a transport for the next client (test hook)."""
    global _transport
    _transport = transport


async def start_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            limits=LIMITS,
            transport=_transport,
            follow_redirects=True,
            headers={"User-Agent": "PulseWatch/1.0 (+uptime monitor)"},
        )
    return _client


async def stop_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_client() -> httpx.AsyncClient:
    """The shared client, created on first use outside the app lifespan."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            limits=LIMITS,
            transport=_transport,
            follow_redirects=True,
            headers={"User-Agent": "PulseWatch/1.0 (+uptime monitor)"},
        )
    return _client
