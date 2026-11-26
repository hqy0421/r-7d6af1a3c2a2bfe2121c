"""Status pages: managed by their owner, read by anyone."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import APIError
from app.core.rate_limit import RateLimiter
from app.db.session import get_db
from app.models import Incident, Monitor, MonitorStatus, StatusPage, User
from app.schemas.monitoring import (
    PublicIncident,
    PublicService,
    PublicStatusPage,
    StatusPageCreate,
    StatusPageOut,
    StatusPageUpdate,
)
from app.services import uptime as uptime_service

router = APIRouter(prefix="/api", tags=["status pages"])
public_limit = RateLimiter(times=120, seconds=60, scope="status-page")

RECENT_INCIDENT_DAYS = 14


def _owned(db: Session, user: User, page_id: int) -> StatusPage:
    page = db.get(StatusPage, page_id)
    if page is None or page.user_id != user.id:
        raise APIError("not_found", "Status page not found.", 404)
    return page


@router.get("/status-pages", response_model=list[StatusPageOut], summary="List status pages")
def list_pages(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(
        db.execute(
            select(StatusPage).where(StatusPage.user_id == user.id).order_by(StatusPage.created_at)
        ).scalars().all()
    )


@router.post("/status-pages", response_model=StatusPageOut, status_code=201, summary="Create one")
def create_page(
    payload: StatusPageCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatusPage:
    if db.execute(select(StatusPage).where(StatusPage.slug == payload.slug)).scalar_one_or_none():
        raise APIError("slug_taken", "That address is already in use.", 409)

    owned = {
        monitor_id
        for monitor_id in db.execute(
            select(Monitor.id).where(Monitor.user_id == user.id)
        ).scalars().all()
    }
    unknown = [mid for mid in payload.monitor_ids if mid not in owned]
    if unknown:
        raise APIError("unknown_monitor", "A selected monitor does not exist.", 422)

    page = StatusPage(
        user_id=user.id,
        slug=payload.slug,
        title=payload.title,
        description=payload.description,
        monitor_ids=payload.monitor_ids,
        published=payload.published,
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    return page


@router.patch("/status-pages/{page_id}", response_model=StatusPageOut, summary="Update")
def update_page(
    payload: StatusPageUpdate,
    page_id: int = Path(ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatusPage:
    page = _owned(db, user, page_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise APIError("nothing_to_update", "No fields to update.", 400)

    if "monitor_ids" in changes and changes["monitor_ids"] is not None:
        owned = set(
            db.execute(select(Monitor.id).where(Monitor.user_id == user.id)).scalars().all()
        )
        if any(mid not in owned for mid in changes["monitor_ids"]):
            raise APIError("unknown_monitor", "A selected monitor does not exist.", 422)

    for field, value in changes.items():
        if value is not None:
            setattr(page, field, value)
    db.commit()
    db.refresh(page)
    return page


@router.delete("/status-pages/{page_id}", status_code=204, summary="Delete")
def delete_page(
    page_id: int = Path(ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    db.delete(_owned(db, user, page_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/status/{slug}",
    response_model=PublicStatusPage,
    tags=["public"],
    summary="Public status page (no authentication)",
)
def public_status(
    slug: str = Path(min_length=2, max_length=48),
    db: Session = Depends(get_db),
    _: None = Depends(public_limit),
) -> PublicStatusPage:
    """Open to the world, so it exposes only what a visitor needs: service
    names, their state, uptime and recent incidents — never URLs or config."""
    page = db.execute(
        select(StatusPage).where(StatusPage.slug == slug.lower())
    ).scalar_one_or_none()
    if page is None or not page.published:
        raise APIError("not_found", "Status page not found.", 404)

    monitors = (
        db.execute(select(Monitor).where(Monitor.id.in_(page.monitor_ids))).scalars().all()
        if page.monitor_ids
        else []
    )
    order = {monitor_id: index for index, monitor_id in enumerate(page.monitor_ids)}
    monitors.sort(key=lambda monitor: order.get(monitor.id, 0))

    services = [
        PublicService(
            name=monitor.name,
            status=monitor.status,
            uptime_24h=uptime_service.uptime(db, monitor.id, "24h")["uptime"],
            uptime_30d=uptime_service.uptime(db, monitor.id, "30d")["uptime"],
            last_checked_at=monitor.last_checked_at,
        )
        for monitor in monitors
    ]

    if any(service.status == MonitorStatus.DOWN for service in services):
        overall = "major_outage"
    elif any(service.status == MonitorStatus.DEGRADED for service in services):
        overall = "degraded"
    elif services and all(
        service.status in (MonitorStatus.OPERATIONAL, MonitorStatus.PAUSED) for service in services
    ):
        overall = "operational"
    else:
        overall = "unknown"

    since = datetime.now(timezone.utc) - timedelta(days=RECENT_INCIDENT_DAYS)
    incidents = (
        db.execute(
            select(Incident, Monitor.name)
            .join(Monitor, Monitor.id == Incident.monitor_id)
            .where(Incident.monitor_id.in_([m.id for m in monitors]), Incident.started_at >= since)
            .order_by(Incident.started_at.desc())
            .limit(20)
        ).all()
        if monitors
        else []
    )

    return PublicStatusPage(
        slug=page.slug,
        title=page.title,
        description=page.description,
        overall=overall,
        services=services,
        incidents=[
            PublicIncident(
                id=incident.id,
                service=name,
                status=incident.status,
                reason=incident.reason,
                started_at=incident.started_at,
                resolved_at=incident.resolved_at,
                duration_seconds=incident.duration_seconds,
                timeline=incident.timeline or [],
            )
            for incident, name in incidents
        ],
        updated_at=datetime.now(timezone.utc),
    )
