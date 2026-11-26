"""FastAPI application entry point.

The scheduler lives inside this process: one asyncio task alongside the API.
That is the right shape for a single-instance deployment and keeps the project
runnable with two commands — the trade-offs are written down in the README
under "Known production limitations".
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, channels, demo, incidents, monitors, status_pages, system
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.db.session import init_db
from app.services.http_client import start_client, stop_client
from app.services.scheduler import scheduler

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)
logger = logging.getLogger("pulsewatch")

DESCRIPTION = """
PulseWatch checks HTTP endpoints on a schedule, records every result, opens an
incident when failures cross a threshold, and tells you about it.

* **`/api/*`** is the management API, authenticated with a session cookie.
* **`/api/status/{slug}`** is public: it powers status pages and exposes no
  configuration.
* **`/demo/*`** are predictable targets (healthy, slow, error, flaky) so the
  product can be demonstrated without depending on someone else's uptime.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    await start_client()
    if settings.scheduler_enabled:
        await scheduler.start()
    else:
        logger.warning("Scheduler disabled (SCHEDULER_ENABLED=false); no checks will run")
    yield
    await scheduler.stop()
    await stop_client()


app = FastAPI(
    title="PulseWatch API",
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

install_error_handlers(app)

for router in (
    system.router, auth.router, monitors.router, monitors.budget_flat_router,
    incidents.router, channels.router, status_pages.router, demo.router,
):
    app.include_router(router)


@app.get("/", include_in_schema=False)
def index() -> JSONResponse:
    return JSONResponse({"service": "pulsewatch-api", "docs": "/docs", "health": "/api/health"})
