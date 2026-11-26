"""Monitor CRUD, manual checks, per-monitor checks and incidents."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_owned_monitor
from app.core.config import settings
from app.core.errors import APIError
from app.core.net import UnsafeTargetError, validate_target
from app.db.base import utcnow
from app.db.session import get_db
from app.models import Incident, IncidentStatus, Monitor, MonitorCheck, MonitorStatus, User
from app.schemas.monitor import MonitorCreate, MonitorDetail, MonitorOut, MonitorUpdate
from app.schemas.monitoring import (
    CheckOut,
    CheckPage,
    IncidentOut,
    IncidentPage,
    ManualCheckResult,
)
from app.services import scheduler as scheduler_service
from app.services import uptime as uptime_service

router = APIRouter(prefix="/api/monitors", tags=["monitors"])

MAX_MONITORS_PER_USER = 50


def _validate_url(url: str) -> str:
    try:
        return validate_target(url)
    except UnsafeTargetError as exc:
        raise APIError("unsafe_target", str(exc), 422) from exc


def to_out(db: Session, monitor: Monitor, model=MonitorOut, **extra) -> MonitorOut:
    open_incident = db.execute(
        select(Incident.id).where(
            Incident.monitor_id == monitor.id, Incident.status == IncidentStatus.OPEN
        )
    ).scalar_one_or_none()
    return model(
        **MonitorOut.model_validate(monitor).model_dump(
            exclude={"uptime_24h", "sparkline", "open_incident_id"}
        ),
        uptime_24h=uptime_service.uptime(db, monitor.id, "24h")["uptime"],
        sparkline=uptime_service.sparkline(db, monitor.id),
        open_incident_id=open_incident,
        **extra,
    )


@router.get("", response_model=list[MonitorOut], summary="List monitors")
def list_monitors(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[MonitorOut]:
    monitors = db.execute(
        select(Monitor).where(Monitor.user_id == user.id).order_by(Monitor.created_at)
    ).scalars().all()
    return [to_out(db, monitor) for monitor in monitors]


@router.post("", response_model=MonitorOut, status_code=201, summary="Create a monitor")
def create_monitor(
    payload: MonitorCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    total = db.execute(
        select(func.count()).select_from(Monitor).where(Monitor.user_id == user.id)
    ).scalar_one()
    if total >= MAX_MONITORS_PER_USER:
        raise APIError(
            "monitor_limit_reached",
            f"This account is limited to {MAX_MONITORS_PER_USER} monitors.",
            409,
        )

    monitor = Monitor(
        user_id=user.id,
        name=payload.name,
        url=_validate_url(payload.url),
        method=payload.method,
        headers=payload.headers,
        interval_seconds=payload.interval_seconds,
        timeout_seconds=payload.timeout_seconds,
        expected_status=payload.expected_status,
        failure_threshold=payload.failure_threshold or settings.default_failure_threshold,
        degraded_ms=payload.degraded_ms or settings.default_degraded_ms,
        enabled=payload.enabled,
        status=MonitorStatus.PENDING if payload.enabled else MonitorStatus.PAUSED,
        next_check_at=utcnow(),
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return to_out(db, monitor)


@router.get("/{monitor_id}", response_model=MonitorDetail, summary="Monitor detail")
def get_monitor(
    monitor: Monitor = Depends(get_owned_monitor),
    db: Session = Depends(get_db),
    hours: int = Query(default=24, ge=1, le=720),
) -> MonitorDetail:
    return to_out(
        db,
        monitor,
        MonitorDetail,
        uptime={window: uptime_service.uptime(db, monitor.id, window) for window in ("24h", "7d", "30d")},
        response_series=uptime_service.response_series(db, monitor.id, hours=hours),
        avg_response_ms=uptime_service.average_response_ms(db, [monitor.id], hours=hours),
    )


@router.patch("/{monitor_id}", response_model=MonitorOut, summary="Update a monitor")
def update_monitor(
    payload: MonitorUpdate,
    monitor: Monitor = Depends(get_owned_monitor),
    db: Session = Depends(get_db),
) -> MonitorOut:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise APIError("nothing_to_update", "No fields to update.", 400)

    if "url" in changes and changes["url"]:
        monitor.url = _validate_url(changes.pop("url"))
    if "enabled" in changes:
        enabled = changes.pop("enabled")
        if enabled:
            scheduler_service.resume(db, monitor)
        else:
            scheduler_service.pause(db, monitor)
    for field, value in changes.items():
        if value is not None:
            setattr(monitor, field, value)

    db.commit()
    db.refresh(monitor)
    return to_out(db, monitor)


@router.delete("/{monitor_id}", status_code=204, summary="Delete a monitor")
def delete_monitor(
    monitor: Monitor = Depends(get_owned_monitor), db: Session = Depends(get_db)
) -> Response:
    db.delete(monitor)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{monitor_id}/check",
    response_model=ManualCheckResult,
    summary="Run a check now",
)
async def run_check_now(
    monitor: Monitor = Depends(get_owned_monitor), db: Session = Depends(get_db)
) -> ManualCheckResult:
    """A real check against the real target — the same engine the scheduler uses."""
    check, _ = await scheduler_service.run_manual_check(db, monitor)
    db.refresh(monitor)
    return ManualCheckResult(
        outcome=check.outcome,
        status_code=check.status_code,
        response_ms=check.response_ms,
        error=check.error,
        monitor_status=monitor.status,
        checked_at=check.checked_at,
    )


@router.get("/{monitor_id}/checks", response_model=CheckPage, summary="Check history")
def list_checks(
    monitor: Monitor = Depends(get_owned_monitor),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CheckPage:
    items = db.execute(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(MonitorCheck.checked_at.desc(), MonitorCheck.id.desc())
        .offset(offset).limit(limit)
    ).scalars().all()
    total = db.execute(
        select(func.count()).select_from(MonitorCheck).where(MonitorCheck.monitor_id == monitor.id)
    ).scalar_one()
    return CheckPage(
        items=[CheckOut.model_validate(item) for item in items],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{monitor_id}/incidents", response_model=IncidentPage, summary="Incident history")
def list_monitor_incidents(
    monitor: Monitor = Depends(get_owned_monitor),
    db: Session = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> IncidentPage:
    items = db.execute(
        select(Incident)
        .where(Incident.monitor_id == monitor.id)
        .order_by(Incident.started_at.desc())
        .offset(offset).limit(limit)
    ).scalars().all()
    total = db.execute(
        select(func.count()).select_from(Incident).where(Incident.monitor_id == monitor.id)
    ).scalar_one()
    return IncidentPage(
        items=[
            IncidentOut(
                **IncidentOut.model_validate(item).model_dump(
                    exclude={"monitor_name", "monitor_url"}
                ),
                monitor_name=monitor.name,
                monitor_url=monitor.url,
            )
            for item in items
        ],
        total=total, limit=limit, offset=offset,
    )
