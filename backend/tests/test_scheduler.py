"""The scheduler: claiming, concurrency and the loop."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models import Monitor
from app.schemas.common import utc_iso
from app.services.scheduler import MonitorScheduler, scheduler


def _due_now(monitor_id: int) -> None:
    with SessionLocal() as db:
        monitor = db.get(Monitor, monitor_id)
        monitor.next_check_at = utcnow()
        db.commit()


def test_claiming_pushes_the_next_check_forward(auth_client: TestClient, make_monitor) -> None:
    """A check that outlives its interval must not be started twice."""
    monitor = make_monitor()
    _due_now(monitor["id"])

    first = scheduler._claim_due()  # noqa: SLF001
    assert [item.id for item in first] == [monitor["id"]]

    # Immediately claiming again finds nothing: the row was moved on in the
    # same transaction that selected it.
    assert scheduler._claim_due() == []  # noqa: SLF001

    with SessionLocal() as db:
        refreshed = db.get(Monitor, monitor["id"])
    # SQLite returns naive datetimes; they are UTC (see schemas.common).
    assert utc_iso(refreshed.next_check_at) > utc_iso(utcnow())


def test_paused_monitors_are_never_claimed(auth_client: TestClient, make_monitor) -> None:
    monitor = make_monitor()
    auth_client.patch(f"/api/monitors/{monitor['id']}", json={"enabled": False})
    _due_now(monitor["id"])
    assert scheduler._claim_due() == []  # noqa: SLF001


def test_the_jitter_keeps_the_interval_honest(auth_client: TestClient, make_monitor) -> None:
    """Jitter spreads the herd without changing what the interval means."""
    monitor = make_monitor(interval_seconds=100)
    with SessionLocal() as db:
        row = db.get(Monitor, monitor["id"])
        delays = [MonitorScheduler._next_delay(row) for _ in range(50)]  # noqa: SLF001

    assert all(90 <= delay <= 110 for delay in delays)
    assert len(set(round(delay, 3) for delay in delays)) > 1  # actually varies


async def test_a_tick_runs_due_checks_and_records_them(
    auth_client: TestClient, make_monitor
) -> None:
    monitor = make_monitor("/demo/healthy")
    _due_now(monitor["id"])

    # tick() works without the loop running, which is what makes the scheduler
    # testable a tick at a time.
    engine = MonitorScheduler()
    started = await engine.tick()
    assert started == 1
    # Let the worker finish; the tick only launches it.
    await asyncio.wait_for(asyncio.gather(*engine._workers), timeout=10)  # noqa: SLF001

    checks = auth_client.get(f"/api/monitors/{monitor['id']}/checks").json()
    assert checks["total"] == 1
    assert checks["items"][0]["outcome"] == "up"
    assert checks["items"][0]["manual"] is False
    assert engine.checks_run == 1


async def test_concurrent_checks_are_bounded(auth_client: TestClient, make_monitor) -> None:
    """Ten monitors coming due together must not open ten sockets at once."""
    from app.core.config import settings

    original = settings.max_concurrent_checks
    settings.max_concurrent_checks = 2
    try:
        for index in range(6):
            monitor = make_monitor("/demo/healthy", name=f"m{index}")
            _due_now(monitor["id"])

        engine = MonitorScheduler()
        await engine.tick()
        await asyncio.wait_for(asyncio.gather(*engine._workers), timeout=15)  # noqa: SLF001
    finally:
        settings.max_concurrent_checks = original

    assert engine.checks_run == 6
    # Every monitor recorded exactly one check, so nothing was dropped by the
    # semaphore — it delayed work rather than discarding it.
    for monitor in auth_client.get("/api/monitors").json():
        checks = auth_client.get(f"/api/monitors/{monitor['id']}/checks").json()
        assert checks["total"] == 1
