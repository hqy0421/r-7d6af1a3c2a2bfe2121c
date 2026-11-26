"""A monitored endpoint and its current state.

The scheduler reads ``next_check_at`` to decide what is due, and the incident
engine reads ``consecutive_failures`` to decide when a wobble becomes an
outage. Both live on the row so a restart resumes exactly where it stopped.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow

if TYPE_CHECKING:
    from app.models.incident import Incident
    from app.models.monitor_check import MonitorCheck
    from app.models.user import User


class MonitorStatus(StrEnum):
    """What the dashboard shows for a monitor right now."""

    PENDING = "pending"          # created, not checked yet
    OPERATIONAL = "operational"  # last check passed, and was fast enough
    DEGRADED = "degraded"        # passed but slow, or failing below the threshold
    DOWN = "down"                # failures reached the threshold; incident open
    PAUSED = "paused"            # disabled by the user; not scheduled


class Monitor(Base, TimestampMixin):
    __tablename__ = "monitors"
    __table_args__ = (Index("ix_monitors_due", "enabled", "next_check_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    name: Mapped[str] = mapped_column(String(80))
    url: Mapped[str] = mapped_column(String(2048))
    method: Mapped[str] = mapped_column(String(8), default="GET")
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    timeout_seconds: Mapped[float] = mapped_column(Integer, default=10)
    expected_status: Mapped[int] = mapped_column(Integer, default=200)
    failure_threshold: Mapped[int] = mapped_column(Integer, default=3)
    degraded_ms: Mapped[int] = mapped_column(Integer, default=1500)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default=MonitorStatus.PENDING, index=True)

    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    last_response_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    last_error: Mapped[str | None] = mapped_column(String(255), default=None)

    user: Mapped["User"] = relationship(back_populates="monitors")
    checks: Mapped[list["MonitorCheck"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan"
    )
    incidents: Mapped[list["Incident"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan"
    )
