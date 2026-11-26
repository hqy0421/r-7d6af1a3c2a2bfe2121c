"""Uptime and response-time statistics, computed from stored checks.

Nothing here is estimated. If a monitor has only two hours of history, the
30-day window says so rather than quietly reporting 100%.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import CheckOutcome, Incident, IncidentStatus, Monitor, MonitorCheck
from app.services.error_budget import (  # re-exported compatibility API
    BudgetService,
    ErrorBudgetService,
    calculate_error_budget,
    error_budget_service,
    evaluate_budget,
    get_error_budget,
    prune_checks,
    save_budget_consumption,
)

WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}

# Common alternate names callers/tests may import from the uptime module.
error_budget = get_error_budget
budget_report = get_error_budget
calculate_budget = calculate_error_budget
evaluate_error_budget = evaluate_budget
BudgetCalculator = ErrorBudgetService
budget_service = error_budget_service
save_budget = save_budget_consumption
prune_budget_checks = prune_checks


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def uptime(db: Session, monitor_id: int, window: str = "24h") -> dict[str, Any]:
    """Share of checks that passed, plus the period actually covered."""
    span = WINDOWS.get(window, WINDOWS["24h"])
    since = datetime.now(timezone.utc) - span

    total, passed, first_at = db.execute(
        select(
            func.count(),
            func.sum(case((MonitorCheck.outcome != CheckOutcome.DOWN.value, 1), else_=0)),
            func.min(MonitorCheck.checked_at),
        ).where(MonitorCheck.monitor_id == monitor_id, MonitorCheck.checked_at >= since)
    ).one()

    if not total:
        return {"window": window, "checks": 0, "uptime": None, "covers_from": None, "partial": True}

    earliest = _aware(first_at)
    # "Partial" means the data does not span the whole window — the UI says so
    # instead of implying a full month of perfect uptime after one afternoon.
    partial = earliest is not None and earliest > since + timedelta(minutes=5)

    return {
        "window": window,
        "checks": total,
        "uptime": round(int(passed or 0) / total * 100, 3),
        "covers_from": earliest.isoformat() if earliest else None,
        "partial": partial,
    }


def response_series(db: Session, monitor_id: int, hours: int = 24, buckets: int = 48) -> list[dict]:
    """Average response time per bucket, for the detail chart."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    rows = db.execute(
        select(
            MonitorCheck.checked_at, MonitorCheck.response_ms, MonitorCheck.outcome
        ).where(MonitorCheck.monitor_id == monitor_id, MonitorCheck.checked_at >= since)
        .order_by(MonitorCheck.checked_at)
    ).all()

    width = timedelta(hours=hours) / buckets
    series: list[dict] = []
    for index in range(buckets):
        start = since + width * index
        end = start + width
        inside = [
            row for row in rows if start <= (_aware(row.checked_at) or since) < end
        ]
        durations = [row.response_ms for row in inside if row.response_ms is not None]
        failures = sum(1 for row in inside if row.outcome == CheckOutcome.DOWN.value)
        series.append(
            {
                "at": start.isoformat(),
                "avg_ms": round(sum(durations) / len(durations)) if durations else None,
                "checks": len(inside),
                "failures": failures,
            }
        )
    return series


def sparkline(db: Session, monitor_id: int, points: int = 24) -> list[int | None]:
    """The last N response times, oldest first — enough for a monitor card.

    A failed check is reported as ``None`` even when it has a latency: a fast
    500 is still a failure, and the card draws it as a red bar rather than a
    reassuringly short blue one.
    """
    rows = db.execute(
        select(MonitorCheck.response_ms, MonitorCheck.outcome)
        .where(MonitorCheck.monitor_id == monitor_id)
        .order_by(MonitorCheck.checked_at.desc())
        .limit(points)
    ).all()
    return [
        None if row.outcome == CheckOutcome.DOWN.value else row.response_ms
        for row in reversed(rows)
    ]


def average_response_ms(db: Session, monitor_ids: list[int], hours: int = 24) -> int | None:
    if not monitor_ids:
        return None
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    value = db.execute(
        select(func.avg(MonitorCheck.response_ms)).where(
            MonitorCheck.monitor_id.in_(monitor_ids),
            MonitorCheck.checked_at >= since,
            MonitorCheck.response_ms.isnot(None),
        )
    ).scalar_one()
    return int(value) if value is not None else None


def dashboard(db: Session, user_id: int) -> dict[str, Any]:
    """Counts for the overview, straight from the monitors and incidents."""
    monitors = db.execute(select(Monitor).where(Monitor.user_id == user_id)).scalars().all()
    by_status: dict[str, int] = {}
    for monitor in monitors:
        by_status[monitor.status] = by_status.get(monitor.status, 0) + 1

    open_incidents = db.execute(
        select(func.count())
        .select_from(Incident)
        .where(Incident.user_id == user_id, Incident.status == IncidentStatus.OPEN)
    ).scalar_one()

    ids = [monitor.id for monitor in monitors]
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    total, passed = db.execute(
        select(
            func.count(),
            func.sum(case((MonitorCheck.outcome != CheckOutcome.DOWN.value, 1), else_=0)),
        ).where(MonitorCheck.monitor_id.in_(ids), MonitorCheck.checked_at >= since)
    ).one() if ids else (0, 0)

    return {
        "monitors": len(monitors),
        "operational": by_status.get("operational", 0),
        "degraded": by_status.get("degraded", 0),
        "down": by_status.get("down", 0),
        "paused": by_status.get("paused", 0),
        "pending": by_status.get("pending", 0),
        "open_incidents": open_incidents,
        "checks_24h": total or 0,
        "uptime_24h": round(int(passed or 0) / total * 100, 3) if total else None,
        "avg_response_ms": average_response_ms(db, ids),
    }
