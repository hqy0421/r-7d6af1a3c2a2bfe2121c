"""Health and engine introspection."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.scheduler import scheduler

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", summary="Liveness and scheduler state")
def health(db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:  # pragma: no cover - only on a broken DB
        database_ok = False

    return {
        "status": "ok" if database_ok else "degraded",
        "database": "ok" if database_ok else "unavailable",
        "environment": settings.environment,
        "scheduler": {
            "enabled": settings.scheduler_enabled,
            "running": scheduler.running,
            "ticks": scheduler.ticks,
            "checks_run": scheduler.checks_run,
            "started_at": scheduler.started_at.isoformat() if scheduler.started_at else None,
            "max_concurrent_checks": settings.max_concurrent_checks,
        },
        "notifications_dry_run": settings.notifications_dry_run,
    }
