"""One HTTP check. These rows are the source of truth for uptime and charts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.monitor import Monitor


class CheckOutcome(StrEnum):
    UP = "up"                # response matched the expectation
    DEGRADED = "degraded"    # matched, but slower than the monitor allows
    DOWN = "down"            # wrong status, timeout, DNS or connection error


class MonitorCheck(Base):
    __tablename__ = "monitor_checks"
    __table_args__ = (
        # Uptime windows, charts and history all read a monitor's checks over a
        # time range; this is the index that makes those queries cheap.
        Index("ix_checks_monitor_time", "monitor_id", "checked_at"),
        Index("ix_checks_outcome_time", "outcome", "checked_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), index=True
    )

    outcome: Mapped[str] = mapped_column(String(16))
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    response_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    error: Mapped[str | None] = mapped_column(String(255), default=None)
    # True when a person pressed "Run check now" instead of the scheduler.
    manual: Mapped[bool] = mapped_column(Boolean, default=False)

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    monitor: Mapped["Monitor"] = relationship(back_populates="checks")

    @property
    def ok(self) -> bool:
        return self.outcome in (CheckOutcome.UP, CheckOutcome.DEGRADED)
