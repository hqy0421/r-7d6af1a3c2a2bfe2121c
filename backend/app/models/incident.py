"""An outage: opened when failures cross the threshold, closed on recovery."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.monitor import Monitor


class IncidentStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_monitor_status", "monitor_id", "status"),
        Index("ix_incidents_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    status: Mapped[str] = mapped_column(String(16), default=IncidentStatus.OPEN)
    reason: Mapped[str] = mapped_column(String(255))
    failure_count: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, default=None)

    # Append-only trail: detected → failing checks → recovered, plus alert
    # delivery. Each entry is {at, kind, message}.
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    monitor: Mapped["Monitor"] = relationship(back_populates="incidents")
