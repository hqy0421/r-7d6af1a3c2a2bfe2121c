"""The check engine: one HTTP request, classified.

Everything here is pure with respect to the database — it takes a target and
returns a result — which is what makes the engine straightforward to test and
lets the scheduler decide when and how often it runs.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.net import UnsafeTargetError, validate_target
from app.models.monitor_check import CheckOutcome
from app.services.http_client import get_client

logger = logging.getLogger("pulsewatch.checker")

# Response bodies are not stored, but a monitor could point at a huge file;
# reading it would waste time and memory that the check does not need.
MAX_BODY_BYTES = 64 * 1024


@dataclass(slots=True)
class CheckTarget:
    """What a check needs to know. Mirrors the monitor row's relevant fields."""

    url: str
    method: str = "GET"
    headers: dict[str, str] | None = None
    timeout_seconds: float = 10.0
    expected_status: int = 200
    degraded_ms: int = 1500


@dataclass(slots=True)
class CheckResult:
    outcome: CheckOutcome
    status_code: int | None = None
    response_ms: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in (CheckOutcome.UP, CheckOutcome.DEGRADED)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": str(self.outcome),
            "status_code": self.status_code,
            "response_ms": self.response_ms,
            "error": self.error,
        }


async def run_check(target: CheckTarget) -> CheckResult:
    """Perform one check. Never raises: a failure *is* the result."""
    try:
        url = validate_target(target.url)
    except UnsafeTargetError as exc:
        return CheckResult(CheckOutcome.DOWN, error=str(exc)[:255])

    timeout = min(target.timeout_seconds, settings.max_check_timeout_seconds)
    client = get_client()
    started = time.perf_counter()

    try:
        request = client.build_request(
            target.method.upper(),
            url,
            headers=target.headers or None,
            timeout=timeout,
        )
        response = await client.send(request, stream=True)
        try:
            # Read a bounded prefix: the body is not stored, but the time to
            # first byte alone would understate a slow endpoint.
            read = 0
            async for chunk in response.aiter_bytes():
                read += len(chunk)
                if read >= MAX_BODY_BYTES:
                    break
        finally:
            await response.aclose()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
    except httpx.TimeoutException:
        return CheckResult(
            CheckOutcome.DOWN,
            response_ms=int((time.perf_counter() - started) * 1000),
            error=f"Timeout after {timeout:g}s",
        )
    except httpx.TooManyRedirects:
        return CheckResult(CheckOutcome.DOWN, error="Too many redirects")
    except httpx.ConnectError as exc:
        return CheckResult(CheckOutcome.DOWN, error=_connection_error(exc))
    except httpx.HTTPError as exc:
        return CheckResult(CheckOutcome.DOWN, error=f"{type(exc).__name__}: {exc}"[:255])
    except Exception as exc:  # noqa: BLE001 - an unexpected bug is a down check, not a crash
        logger.exception("Unexpected error checking %s", target.url)
        return CheckResult(CheckOutcome.DOWN, error=f"Check failed: {type(exc).__name__}")

    if response.status_code != target.expected_status:
        return CheckResult(
            CheckOutcome.DOWN,
            status_code=response.status_code,
            response_ms=elapsed_ms,
            error=f"Expected {target.expected_status}, got {response.status_code}",
        )

    outcome = CheckOutcome.DEGRADED if elapsed_ms > target.degraded_ms else CheckOutcome.UP
    return CheckResult(outcome, status_code=response.status_code, response_ms=elapsed_ms)


def _connection_error(exc: httpx.ConnectError) -> str:
    text = str(exc)
    if "Name or service not known" in text or "nodename nor servname" in text:
        return "DNS lookup failed"
    if "Connection refused" in text:
        return "Connection refused"
    if "certificate" in text.lower():
        return "TLS certificate error"
    return f"Connection failed: {text}"[:255]
