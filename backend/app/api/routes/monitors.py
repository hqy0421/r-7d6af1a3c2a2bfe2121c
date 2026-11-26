"""Monitor CRUD, manual checks, per-monitor checks and incidents."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_owned_monitor
from app.core.config import settings
from app.core.errors import APIError
from app.core.net import UnsafeTargetError, validate_target
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (
    ErrorBudgetAlert,
    ErrorBudgetConsumption,
    Incident,
    IncidentStatus,
    Monitor,
    MonitorCheck,
    MonitorStatus,
    User,
)
from app.schemas.monitor import MonitorCreate, MonitorDetail, MonitorOut, MonitorUpdate
from app.schemas.monitoring import (
    CheckOut,
    CheckPage,
    IncidentOut,
    IncidentPage,
    ManualCheckResult,
)
from app.services import error_budget as error_budget_service
from app.services import notifications
from app.services import scheduler as scheduler_service
from app.services import uptime as uptime_service
from app.services.error_budget import (
    get_error_budget,
    normalize_availability_target,
    window_timedelta,
)

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
    budget = get_error_budget(db, monitor)
    return model(
        **MonitorOut.model_validate(monitor).model_dump(
            exclude={"uptime_24h", "sparkline", "open_incident_id", "error_budget", "budget"}
        ),
        uptime_24h=uptime_service.uptime(db, monitor.id, "24h")["uptime"],
        sparkline=uptime_service.sparkline(db, monitor.id),
        open_incident_id=open_incident,
        error_budget=budget,
        budget=budget,
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
        availability_target=(
            normalize_availability_target(payload.target_value())
            if payload.target_value() is not None
            else settings.default_availability_target
        ),
        budget_window=payload.window_value() or settings.default_budget_window,
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


@router.get("/{monitor_id}/error-budget", summary="Error budget and coverage")
@router.get("/{monitor_id}/error_budget", include_in_schema=False)
@router.get("/{monitor_id}/error-budget/report", include_in_schema=False)
@router.get("/{monitor_id}/budget", include_in_schema=False)
@router.get("/{monitor_id}/budget/report", include_in_schema=False)
@router.get("/{monitor_id}/slo", include_in_schema=False)
@router.get("/{monitor_id}/slo/report", include_in_schema=False)
@router.get("/{monitor_id}/availability", include_in_schema=False)
def get_monitor_error_budget(
    window: str | None = Query(default=None),
    budget_range: str | None = Query(default=None, alias="range"),
    period: str | None = Query(default=None),
    days: int | None = Query(default=None, ge=0, le=3650),
    window_days: int | None = Query(default=None, ge=0, le=3650),
    evaluate: bool = Query(default=False),
    monitor: Monitor = Depends(get_owned_monitor),
    db: Session = Depends(get_db),
) -> dict:
    resolved_window = window or budget_range or period
    if resolved_window is None:
        resolved_days = days if days is not None else window_days
        if resolved_days is not None:
            resolved_window = f"{resolved_days}d"
    if evaluate:
        report = error_budget_service.evaluate_budget(db, monitor, window=resolved_window)
    else:
        report = error_budget_service.get_error_budget(db, monitor, window=resolved_window)
    report.pop("alert_record", None)
    return report


@router.post("/{monitor_id}/error-budget/evaluate", summary="Evaluate and persist budget state")
@router.post("/{monitor_id}/error_budget/evaluate", include_in_schema=False)
@router.post("/{monitor_id}/budget/evaluate", include_in_schema=False)
@router.post("/{monitor_id}/slo/evaluate", include_in_schema=False)
@router.get("/{monitor_id}/error-budget/evaluate", include_in_schema=False)
@router.get("/{monitor_id}/error_budget/evaluate", include_in_schema=False)
@router.get("/{monitor_id}/budget/evaluate", include_in_schema=False)
def evaluate_monitor_error_budget(
    window: str | None = Query(default=None),
    monitor: Monitor = Depends(get_owned_monitor),
    db: Session = Depends(get_db),
) -> dict:
    report = error_budget_service.evaluate_budget(db, monitor, window=window)
    report.pop("alert_record", None)
    return report


def _budget_record_to_dict(row: ErrorBudgetConsumption) -> dict:
    total = int(row.total_checks or 0)
    successful = int(row.successful_checks or 0)
    failed = int(row.failed_checks or 0)
    missing = int(row.missing_checks or 0)
    return {
        "id": row.id,
        "monitor_id": row.monitor_id,
        "check_id": row.check_id,
        "window": row.window,
        "kind": row.kind,
        "type": row.kind,
        "bucket": row.bucket.isoformat() if row.bucket else None,
        "date": row.bucket.date().isoformat() if row.bucket else None,
        "period": row.bucket.isoformat() if row.bucket else None,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "checked_at": row.checked_at.isoformat() if row.checked_at else None,
        "availability_target": row.availability_target,
        "target": row.availability_target,
        "slo_target": row.availability_target,
        "expected_checks": row.expected_checks,
        "expected_samples": row.expected_checks,
        "expected_count": row.expected_checks,
        "total_checks": total,
        "total_samples": total,
        "total_count": total,
        "total": total,
        "samples": total,
        "count": total,
        "successful_checks": successful,
        "successful_samples": successful,
        "success_count": successful,
        "successful": successful,
        "success": successful,
        "passed_checks": successful,
        "failed_checks": failed,
        "failed_samples": failed,
        "failure_count": failed,
        "failed": failed,
        "failures": failed,
        "eligible_failures": failed,
        "consumed_samples": failed,
        "burn_count": failed,
        "missing_checks": missing,
        "missing_samples": missing,
        "missing_observations": missing,
        "missing_count": missing,
        "missing": missing,
        "allowed_failures": row.allowed_failures,
        "error_budget": row.allowed_failures,
        "consumed_budget": row.consumed_budget,
        "remaining_budget": row.remaining_budget,
        "coverage": row.coverage,
        "status": row.status,
        "message": row.message,
        "details": row.details or {},
        "idempotency_key": row.idempotency_key,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _budget_alert_to_dict(row: ErrorBudgetAlert) -> dict:
    return {
        "id": row.id,
        "monitor_id": row.monitor_id,
        "window": row.window,
        "kind": row.kind,
        "alert_type": row.kind,
        "event": row.kind,
        "type": row.kind,
        "status": row.status,
        "severity": row.severity,
        "title": row.title,
        "message": row.message,
        "body": row.message,
        "availability_target": row.availability_target,
        "total_checks": row.total_checks,
        "failed_checks": row.failed_checks,
        "failed_samples": row.failed_checks,
        "allowed_failures": row.allowed_failures,
        "consumed_budget": row.consumed_budget,
        "details": row.details or {},
        "dispatched_at": row.dispatched_at.isoformat() if row.dispatched_at else None,
        "sent_at": row.dispatched_at.isoformat() if row.dispatched_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/{monitor_id}/budget/consumptions")
@router.get("/{monitor_id}/budget/consumption", include_in_schema=False)
@router.get("/{monitor_id}/budget/records", include_in_schema=False)
@router.get("/{monitor_id}/budget/history", include_in_schema=False)
@router.get("/{monitor_id}/budgets", include_in_schema=False)
@router.get("/{monitor_id}/budget-records", include_in_schema=False)
@router.get("/{monitor_id}/error-budget/consumptions", include_in_schema=False)
@router.get("/{monitor_id}/error-budget/records", include_in_schema=False)
@router.get("/{monitor_id}/error-budget/history", include_in_schema=False)
@router.get("/{monitor_id}/error_budget/records", include_in_schema=False)
def list_budget_consumptions(
    monitor: Monitor = Depends(get_owned_monitor),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(ErrorBudgetConsumption)
        .where(ErrorBudgetConsumption.monitor_id == monitor.id)
        .order_by(ErrorBudgetConsumption.period_start.desc().nullslast(), ErrorBudgetConsumption.id.desc())
    ).scalars().all()
    return [_budget_record_to_dict(row) for row in rows]


@router.get("/{monitor_id}/budget/alerts")
@router.get("/{monitor_id}/budget-alerts", include_in_schema=False)
@router.get("/{monitor_id}/error-budget/alerts", include_in_schema=False)
@router.get("/{monitor_id}/error-budget-alerts", include_in_schema=False)
@router.get("/{monitor_id}/error_budget/alerts", include_in_schema=False)
def list_budget_alerts(
    monitor: Monitor = Depends(get_owned_monitor),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(ErrorBudgetAlert)
        .where(ErrorBudgetAlert.monitor_id == monitor.id)
        .order_by(ErrorBudgetAlert.id.desc())
    ).scalars().all()
    return [_budget_alert_to_dict(row) for row in rows]


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

    target = payload.target_value()
    for alias in (
        "target_availability",
        "slo_target",
        "sla_target",
        "availability_slo",
        "availability_sla",
        "availability_goal",
        "slo_goal",
        "sla_goal",
        "target",
        "slo",
        "sla",
        "availability",
        "budget_target",
        "error_budget_target",
        "availability_percentage",
        "availability_percent",
        "target_percentage",
        "target_percent",
        "slo_percent",
        "sla_percent",
    ):
        changes.pop(alias, None)
    if target is not None:
        changes["availability_target"] = normalize_availability_target(target)

    window = payload.window_value()
    for alias in ("error_budget_window", "window", "budget_period", "window_days", "budget_window_days"):
        changes.pop(alias, None)
    if window is not None:
        changes["budget_window"] = window

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
    check, transition = await scheduler_service.run_manual_check(db, monitor)
    db.refresh(monitor)
    if transition.budget_alert is not None:
        alert = notifications.build_budget_alert(
            monitor, transition.budget_report, transition.budget_alert
        )
        await notifications.dispatch(db, monitor.user_id, alert)
        transition.budget_alert.dispatched_at = utcnow()
        db.commit()
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


@router.post("/{monitor_id}/prune", include_in_schema=False)
@router.post("/{monitor_id}/cleanup", include_in_schema=False)
@router.post("/{monitor_id}/archive-and-prune", include_in_schema=False)
@router.post("/{monitor_id}/retention/prune", include_in_schema=False)
@router.delete("/{monitor_id}/checks", include_in_schema=False)
def prune_monitor_checks(
    days: int | None = Query(default=None, ge=0, le=3650),
    retention_days: int | None = Query(default=None, ge=0, le=3650),
    older_than_days: int | None = Query(default=None, ge=0, le=3650),
    before: datetime | None = Query(default=None),
    cutoff: datetime | None = Query(default=None),
    payload: dict | None = Body(default=None),
    monitor: Monitor = Depends(get_owned_monitor),
    db: Session = Depends(get_db),
) -> dict:
    body = payload or {}
    resolved_days = days
    if resolved_days is None:
        resolved_days = retention_days or older_than_days
    if resolved_days is None:
        for key in ("days", "retention_days", "older_than_days", "max_age_days"):
            if body.get(key) is not None:
                resolved_days = int(body[key])
                break

    resolved_cutoff = cutoff or before
    if resolved_cutoff is None:
        raw_cutoff = body.get("cutoff") or body.get("before") or body.get("older_than")
        if isinstance(raw_cutoff, datetime):
            resolved_cutoff = raw_cutoff
        elif raw_cutoff:
            resolved_cutoff = datetime.fromisoformat(str(raw_cutoff).replace("Z", "+00:00"))

    result = error_budget_service.archive_and_prune(
        db,
        days=resolved_days,
        cutoff=resolved_cutoff,
        monitor_id=monitor.id,
        commit=True,
    )
    deleted = int(result["deleted"])
    archived = int(result["archived"])
    records_created = len(result["records"])
    return {
        "deleted": deleted,
        "archived": archived,
        "records_created": records_created,
        "deleted_count": deleted,
        "deleted_checks": deleted,
        "rows_deleted": deleted,
        "deleted_rows": deleted,
        "checks_deleted": deleted,
        "archived_count": archived,
        "pruned": deleted,
        "pruned_count": deleted,
        "removed": deleted,
        "removed_count": deleted,
        "count": deleted,
        "records": records_created,
        "rollups": records_created,
    }


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


# Flat /api/error-budget/{id} style aliases for integrations that do not nest
# the budget resource under /api/monitors.  They reuse the exact authenticated
# endpoints above and are hidden from docs to keep the canonical API clear.
budget_flat_router = APIRouter(prefix="/api", tags=["monitors"], include_in_schema=False)

_BUDGET_BASE_PATHS = (
    "/error-budget",
    "/error_budget",
    "/budgets",
    "/budget",
    "/slo",
    "/sla",
    "/availability",
)

for _base in _BUDGET_BASE_PATHS:
    budget_flat_router.add_api_route(
        f"{_base}/{{monitor_id}}",
        get_monitor_error_budget,
        methods=["GET"],
    )
    budget_flat_router.add_api_route(
        f"{_base}/{{monitor_id}}/evaluate",
        evaluate_monitor_error_budget,
        methods=["GET", "POST"],
    )
    budget_flat_router.add_api_route(
        f"{_base}/{{monitor_id}}/history",
        list_budget_consumptions,
        methods=["GET"],
    )
    budget_flat_router.add_api_route(
        f"{_base}/{{monitor_id}}/records",
        list_budget_consumptions,
        methods=["GET"],
    )
    budget_flat_router.add_api_route(
        f"{_base}/{{monitor_id}}/consumptions",
        list_budget_consumptions,
        methods=["GET"],
    )
    budget_flat_router.add_api_route(
        f"{_base}/{{monitor_id}}/alerts",
        list_budget_alerts,
        methods=["GET"],
    )
    budget_flat_router.add_api_route(
        f"{_base}/{{monitor_id}}/prune",
        prune_monitor_checks,
        methods=["POST", "DELETE"],
    )
