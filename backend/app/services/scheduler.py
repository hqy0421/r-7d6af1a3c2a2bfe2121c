"""The monitoring scheduler.

One asyncio task drives everything. Every tick it claims the monitors that are
due, hands each to a bounded worker, and moves on — a slow endpoint delays its
own next check and nothing else.

Three details matter more than the loop itself:

* **Claiming.** Due monitors get their ``next_check_at`` pushed forward in the
  same transaction that selects them, so a check that outlives its interval is
  never started twice.
* **Bounded concurrency.** A semaphore caps checks in flight; a hundred
  monitors coming due together queue instead of opening a hundred sockets.
* **Jitter.** Monitors created in the same second would otherwise stay in
  lockstep forever, producing a spike every interval.

Blocking database work runs in worker threads, so the loop keeps ticking while
SQLite (or PostgreSQL) does its job.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models import Incident, Monitor, MonitorStatus
from app.services import incidents as incident_engine
from app.services import notifications
from app.services.checker import CheckResult, CheckTarget, run_check

logger = logging.getLogger("pulsewatch.scheduler")

# Up to ±10% of the interval, capped, so the herd spreads out but the interval
# still means roughly what the user asked for.
MAX_JITTER_SECONDS = 15


@dataclass(slots=True)
class ClaimedMonitor:
    """A snapshot taken under the claim, so the worker touches no ORM state."""

    id: int
    name: str
    target: CheckTarget


class MonitorScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._claim_lock: asyncio.Lock | None = None
        self._workers: set[asyncio.Task[None]] = set()
        self.ticks = 0
        self.checks_run = 0
        self.started_at = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # -- lifecycle ---------------------------------------------------------
    def _bind_to_loop(self) -> None:
        """Create the loop-bound primitives on first use.

        A semaphore and a lock attach to the loop that first awaits them, and
        this object outlives any single loop (reloads, tests), so they are
        created here rather than in __init__.
        """
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.max_concurrent_checks)
        if self._claim_lock is None:
            self._claim_lock = asyncio.Lock()

    async def start(self) -> None:
        if self.running:
            return
        self._bind_to_loop()
        self.started_at = utcnow()
        self._task = asyncio.create_task(self._loop(), name="pulsewatch-scheduler")
        logger.info(
            "Scheduler started (tick=%.1fs, max concurrent checks=%s)",
            settings.scheduler_tick_seconds,
            settings.max_concurrent_checks,
        )

    async def stop(self) -> None:
        """Stop ticking, then let checks already in flight finish."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._workers:
            await asyncio.wait(self._workers, timeout=settings.max_check_timeout_seconds + 5)
        logger.info("Scheduler stopped after %s ticks and %s checks", self.ticks, self.checks_run)

    # -- loop --------------------------------------------------------------
    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad tick must not end monitoring
                logger.exception("Scheduler tick failed")
            await asyncio.sleep(settings.scheduler_tick_seconds)

    async def tick(self) -> int:
        """Claim everything due and start a worker for each. Returns the count.

        The claim is serialised: two overlapping ticks would otherwise read the
        same due rows before either committed and run every check twice.
        """
        self._bind_to_loop()
        assert self._claim_lock is not None
        self.ticks += 1
        async with self._claim_lock:
            claimed = await asyncio.to_thread(self._claim_due)
        for monitor in claimed:
            worker = asyncio.create_task(self._execute(monitor))
            self._workers.add(worker)
            worker.add_done_callback(self._workers.discard)
        return len(claimed)

    def _claim_due(self) -> list[ClaimedMonitor]:
        """Select due monitors and push their next check forward, atomically."""
        now = utcnow()
        claimed: list[ClaimedMonitor] = []
        with SessionLocal() as db:
            due = db.execute(
                select(Monitor)
                .where(Monitor.enabled.is_(True), Monitor.next_check_at <= now)
                .order_by(Monitor.next_check_at)
                .limit(settings.max_concurrent_checks * 4)
            ).scalars().all()

            for monitor in due:
                monitor.next_check_at = now + timedelta(seconds=self._next_delay(monitor))
                claimed.append(
                    ClaimedMonitor(
                        id=monitor.id,
                        name=monitor.name,
                        target=CheckTarget(
                            url=monitor.url,
                            method=monitor.method,
                            headers=dict(monitor.headers or {}),
                            timeout_seconds=float(monitor.timeout_seconds),
                            expected_status=monitor.expected_status,
                            degraded_ms=monitor.degraded_ms,
                        ),
                    )
                )
            db.commit()
        return claimed

    @staticmethod
    def _next_delay(monitor: Monitor) -> float:
        jitter = min(MAX_JITTER_SECONDS, monitor.interval_seconds * 0.1)
        return max(5.0, monitor.interval_seconds + random.uniform(-jitter, jitter))

    # -- one check ---------------------------------------------------------
    async def _execute(self, monitor: ClaimedMonitor) -> None:
        self._bind_to_loop()
        assert self._semaphore is not None
        async with self._semaphore:
            result = await run_check(monitor.target)
        self.checks_run += 1
        await self._persist(monitor.id, result)

    async def _persist(self, monitor_id: int, result: CheckResult) -> None:
        transition = await asyncio.to_thread(self._store, monitor_id, result)
        if transition is None:
            return
        # Alerts are sent from the loop, after the write: a slow webhook delays
        # the alert, never the next check.
        await self._alert(transition)

    @staticmethod
    def _store(monitor_id: int, result: CheckResult):
        with SessionLocal() as db:
            monitor = db.get(Monitor, monitor_id)
            if monitor is None:  # deleted mid-flight
                return None
            _, transition = incident_engine.record_check(db, monitor, result)
            return transition if (transition.incident_opened or transition.incident_resolved) else None

    async def _alert(self, transition) -> None:  # noqa: ANN001
        incident = transition.incident_opened or transition.incident_resolved
        recovered = transition.incident_resolved is not None
        with SessionLocal() as db:
            fresh = db.get(Incident, incident.id)
            monitor = db.get(Monitor, transition.monitor_id)
            if fresh is None or monitor is None:
                return
            alert = notifications.build_alert(monitor, fresh, recovered=recovered)
            results = await notifications.dispatch(db, monitor.user_id, alert)
            if results:
                incident_engine.note(
                    fresh, "notified", f"Alert sent — {'; '.join(results)[:200]}"
                )
                db.commit()
        logger.info("%s alert for monitor %s: %s", alert.kind, transition.monitor_id, results)


scheduler = MonitorScheduler()


async def run_manual_check(db: Session, monitor: Monitor):
    """The "Run check now" button: the same engine, on demand.

    It does not touch the schedule — the next automatic check still happens
    when it was going to.
    """
    target = CheckTarget(
        url=monitor.url,
        method=monitor.method,
        headers=dict(monitor.headers or {}),
        timeout_seconds=float(monitor.timeout_seconds),
        expected_status=monitor.expected_status,
        degraded_ms=monitor.degraded_ms,
    )
    result = await run_check(target)
    check, transition = incident_engine.record_check(db, monitor, result, manual=True)

    if transition.incident_opened or transition.incident_resolved:
        incident = transition.incident_opened or transition.incident_resolved
        alert = notifications.build_alert(
            monitor, incident, recovered=transition.incident_resolved is not None
        )
        await notifications.dispatch(db, monitor.user_id, alert)

    return check, transition


def pause(db: Session, monitor: Monitor) -> None:
    monitor.enabled = False
    monitor.status = MonitorStatus.PAUSED
    db.commit()


def resume(db: Session, monitor: Monitor) -> None:
    monitor.enabled = True
    monitor.status = MonitorStatus.PENDING
    monitor.consecutive_failures = 0
    monitor.next_check_at = utcnow()
    db.commit()
