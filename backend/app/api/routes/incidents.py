"""Incidents across all monitors, and the dashboard summary."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import APIError
from app.db.session import get_db
from app.models import Incident, Monitor, User
from app.schemas.monitoring import DashboardOut, IncidentOut, IncidentPage
from app.services import uptime as uptime_service

router = APIRouter(prefix="/api", tags=["incidents"])


def _serialise(row) -> IncidentOut:  # noqa: ANN001
    incident, name, url = row
    return IncidentOut(
        **IncidentOut.model_validate(incident).model_dump(exclude={"monitor_name", "monitor_url"}),
        monitor_name=name,
        monitor_url=url,
    )


@router.get("/incidents", response_model=IncidentPage, summary="Incidents")
def list_incidents(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
) -> IncidentPage:
    conditions = [Incident.user_id == user.id]
    if status_filter:
        conditions.append(Incident.status == status_filter)

    rows = db.execute(
        select(Incident, Monitor.name, Monitor.url)
        .join(Monitor, Monitor.id == Incident.monitor_id)
        .where(*conditions)
        .order_by(Incident.started_at.desc())
        .offset(offset).limit(limit)
    ).all()
    total = db.execute(
        select(func.count()).select_from(Incident).where(*conditions)
    ).scalar_one()

    return IncidentPage(
        items=[_serialise(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/incidents/{incident_id}", response_model=IncidentOut, summary="Incident detail")
def get_incident(
    incident_id: int = Path(ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncidentOut:
    row = db.execute(
        select(Incident, Monitor.name, Monitor.url)
        .join(Monitor, Monitor.id == Incident.monitor_id)
        .where(Incident.id == incident_id, Incident.user_id == user.id)
    ).first()
    if row is None:
        raise APIError("not_found", "Incident not found.", 404)
    return _serialise(row)


@router.get("/dashboard", response_model=DashboardOut, summary="Dashboard summary")
def dashboard(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DashboardOut:
    return DashboardOut(**uptime_service.dashboard(db, user.id))
