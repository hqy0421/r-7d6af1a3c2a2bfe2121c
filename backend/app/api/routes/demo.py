"""Endpoints that behave predictably, so a demo does not depend on the internet.

``/demo/healthy`` always answers 200 quickly, ``/demo/slow`` takes long enough
to trip the degraded threshold, ``/demo/error`` returns 500, and
``/demo/flaky`` fails roughly a third of the time. They are exempt from the
SSRF guard by identity (see ``app.core.net``), so demos work with the guard on.
"""

from __future__ import annotations

import asyncio
import random

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/demo", tags=["demo targets"])


@router.get("/healthy", summary="Always 200")
async def healthy() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/slow", summary="200, but slowly")
async def slow(seconds: float = Query(default=2.0, ge=0, le=10)) -> dict[str, object]:
    await asyncio.sleep(seconds)
    return {"status": "ok", "slept": seconds}


@router.get("/error", summary="Always 500")
async def error() -> JSONResponse:
    return JSONResponse({"error": {"code": "demo_error", "message": "Simulated failure"}}, 500)


@router.get("/flaky", summary="Fails about a third of the time")
async def flaky() -> JSONResponse:
    if random.random() < 0.34:
        return JSONResponse(
            {"error": {"code": "demo_flaky", "message": "Simulated flake"}}, 503
        )
    return JSONResponse({"status": "ok"}, 200)


@router.get("/timeout", summary="Never answers in time")
async def timeout() -> dict[str, str]:
    await asyncio.sleep(60)
    return {"status": "never"}
