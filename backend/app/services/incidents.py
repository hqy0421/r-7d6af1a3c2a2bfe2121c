"""Turning a stream of check results into monitor state and incidents.

The rules, in full:

* a failing check increments ``consecutive_failures``; a passing one resets it;
* the monitor is ``down`` once the counter reaches its threshold, ``degraded``
  while it is failing below the threshold or answering slowly, and
  ``operational`` otherwise;
* crossing the threshold opens exactly one incident — later failures append to
  it rather than creating duplicates;
* the first passing check after an incident resolves it and records the
  downtime.

Thresholds are why a single dropped packet does not page anyone at 3am.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Incident, IncidentStatus, Monitor, MonitorCheck, MonitorStatus
from app.services.checker import CheckResult

logger = logging.getLogger("pulsewatch.incidents")

MAX_TIMELINE_ENTRIES = 50


@dataclass(slots=True)
class Transition:
    """What changed, so the caller knows whether to alert."""

    monitor_id: int
    previous_status: str
    new_status: str
    incident_opened: Incident | None = None
    incident_resolved: Incident | None = None


def open_incident_reason(result: CheckResult) -> str:
    if result.error:
        return result.error
    if result.status_code is not None:
        return f"Unexpected status {result.status_code}"
    return "Check failed"


def record_check(
    db: Session, monitor: Monitor, result: CheckResult, *, manual: bool = False
) -> tuple[MonitorCheck, Transition]:
    """Store the result, update the monitor, and open or resolve an incident."""
    now = utcnow()
    check = MonitorCheck(
        monitor_id=monitor.id,
        outcome=str(result.outcome),
        status_code=result.status_code,
        response_ms=result.response_ms,
        error=result.error,
        manual=manual,
        checked_at=now,
    )
    db.add(check)

    previous_status = monitor.status
    monitor.last_checked_at = now
    monitor.last_response_ms = result.response_ms
    monitor.last_error = result.error

    transition = Transition(
        monitor_id=monitor.id, previous_status=previous_status, new_status=previous_status
    )
    open_incident = _open_incident(db, monitor)

    if result.ok:
        monitor.consecutive_failures = 0
        monitor.status = (
            MonitorStatus.DEGRADED
            if str(result.outcome) == "degraded"
            else MonitorStatus.OPERATIONAL
        )
        if open_incident is not None:
            _resolve(open_incident, now)
            transition.incident_resolved = open_incident
    else:
        monitor.consecutive_failures += 1
        reached = monitor.consecutive_failures >= monitor.failure_threshold
        monitor.status = MonitorStatus.DOWN if reached else MonitorStatus.DEGRADED

        if reached and open_incident is None:
            incident = Incident(
                monitor_id=monitor.id,
                user_id=monitor.user_id,
                status=IncidentStatus.OPEN,
                reason=open_incident_reason(result),
                failure_count=monitor.consecutive_failures,
                started_at=now,
                timeline=[
                    _entry(
                        now,
                        "detected",
                        f"{monitor.name} is unavailable after "
                        f"{monitor.consecutive_failures} consecutive failed checks "
                        f"({open_incident_reason(result)})",
                    )
                ],
            )
            db.add(incident)
            transition.incident_opened = incident
        elif open_incident is not None:
            # One incident, many failures: the timeline grows, the row does not
            # multiply.
            open_incident.failure_count = monitor.consecutive_failures
            open_incident.timeline = _append(
                open_incident.timeline,
                _entry(now, "failing", f"Check failed: {open_incident_reason(result)}"),
            )

    transition.new_status = monitor.status
    db.commit()
    db.refresh(check)
    return check, transition


def _open_incident(db: Session, monitor: Monitor) -> Incident | None:
    return db.execute(
        select(Incident).where(
            Incident.monitor_id == monitor.id, Incident.status == IncidentStatus.OPEN
        )
    ).scalar_one_or_none()


def _resolve(incident: Incident, now: datetime) -> None:
    started = incident.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = now
    incident.duration_seconds = max(0, int((now - started).total_seconds()))
    incident.timeline = _append(
        incident.timeline,
        _entry(now, "resolved", f"Service recovered after {format_duration(incident.duration_seconds)}"),
    )


def note(incident: Incident, kind: str, message: str) -> None:
    """Append an entry — used for alert delivery and manual notes."""
    incident.timeline = _append(incident.timeline, _entry(utcnow(), kind, message))


def _entry(at: datetime, kind: str, message: str) -> dict[str, str]:
    return {"at": at.isoformat(), "kind": kind, "message": message[:255]}


def _append(timeline: list[dict] | None, entry: dict[str, str]) -> list[dict]:
    """Bounded and copied: JSON columns need a new list to be detected as dirty."""
    entries = list(timeline or [])
    entries.append(entry)
    if len(entries) > MAX_TIMELINE_ENTRIES:
        # Keep the first entry (how it started) and the most recent ones.
        entries = entries[:1] + entries[-(MAX_TIMELINE_ENTRIES - 1):]
    return entries


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"
