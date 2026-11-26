"""One HTTP check. These rows are the source of truth for uptime and charts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

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

    # Set once a budget rollup has durably absorbed this row's counts.  The row
    # may remain briefly so a failed cleanup can retry without aggregating it
    # twice; budget reads then exclude it because the rollup already counts it.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    budget_record_id: Mapped[int | None] = mapped_column(Integer, default=None)

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    monitor: Mapped["Monitor"] = relationship(back_populates="checks")

    @validates("outcome")
    def _normalize_outcome(self, _key: str, value: object) -> str | None:
        if value is None:
            return None
        # Accept uppercase enum spellings and boolean/string compatibility
        # tokens; budget classification is deliberately case-insensitive.
        return str(value).strip().lower()

    @property
    def ok(self) -> bool:
        return self.outcome in (CheckOutcome.UP, CheckOutcome.DEGRADED)

    @ok.setter
    def ok(self, value: bool) -> None:
        # False means an unavailable/down sample.  Degraded remains available
        # and is represented by explicitly setting outcome="degraded".
        self.outcome = CheckOutcome.UP.value if bool(value) else CheckOutcome.DOWN.value

    @property
    def success(self) -> bool:
        return self.ok

    @success.setter
    def success(self, value: bool) -> None:
        self.ok = value

    successful = success
    is_success = success

    @property
    def archived(self) -> bool:
        return self.archived_at is not None
