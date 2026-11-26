"""A monitored endpoint and its current state.

The scheduler reads ``next_check_at`` to decide what is due, and the incident
engine reads ``consecutive_failures`` to decide when a wobble becomes an
outage. Both live on the row so a restart resumes exactly where it stopped.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property

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

    # SLO / error-budget policy.  Percentages use the same 0-100 convention as
    # uptime; 99.9 means at most 0.1% failed eligible samples.
    availability_target: Mapped[float] = mapped_column(Float, default=99.9)
    budget_window: Mapped[str] = mapped_column(String(16), default="30d")
    budget_state: Mapped[str] = mapped_column(String(32), default="within_budget", index=True)
    budget_exhausted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    budget_alert_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    budget_alert_count: Mapped[int] = mapped_column(Integer, default=0)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default=MonitorStatus.PENDING, index=True)

    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    last_response_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    last_error: Mapped[str | None] = mapped_column(String(255), default=None)

    @validates("availability_target")
    def _normalize_availability_target(self, _key: str, value: Any) -> float:
        """Accept both 99.9 (%) and 0.999 (ratio) construction styles."""
        if value is None:
            return 99.9
        normalized = float(value)
        if 0 < normalized <= 1:
            normalized *= 100.0
        return max(0.0, min(100.0, normalized))

    user: Mapped["User"] = relationship(back_populates="monitors")

    @property
    def slo_target(self) -> float:
        return self.availability_target

    @slo_target.setter
    def slo_target(self, value: float) -> None:
        self.availability_target = value

    sla_target = slo_target

    @property
    def availability_slo(self) -> float:
        return self.availability_target

    @availability_slo.setter
    def availability_slo(self, value: float) -> None:
        self.availability_target = value

    availability_sla = availability_slo

    @property
    def target_availability(self) -> float:
        return self.availability_target

    @target_availability.setter
    def target_availability(self, value: float) -> None:
        self.availability_target = value

    @property
    def availability_goal(self) -> float:
        return self.availability_target

    @availability_goal.setter
    def availability_goal(self, value: float) -> None:
        self.availability_target = value

    @property
    def slo_goal(self) -> float:
        return self.availability_target

    @slo_goal.setter
    def slo_goal(self, value: float) -> None:
        self.availability_target = value

    sla_goal = slo_goal

    @property
    def target(self) -> float:
        return self.availability_target

    @target.setter
    def target(self, value: float) -> None:
        self.availability_target = float(value)

    @property
    def slo(self) -> float:
        return self.availability_target

    @slo.setter
    def slo(self, value: float) -> None:
        self.availability_target = float(value)

    sla = slo

    @property
    def availability(self) -> float:
        return self.availability_target

    @availability.setter
    def availability(self, value: float) -> None:
        self.availability_target = float(value)

    availability_percent = availability
    availability_percentage = availability

    budget_target = target

    @property
    def error_budget_target(self) -> float:
        return self.availability_target

    @error_budget_target.setter
    def error_budget_target(self, value: float) -> None:
        self.availability_target = float(value)

    @hybrid_property
    def budget_exhausted(self) -> bool:
        return self.budget_state in {"exhausted", "over_budget", "budget_exhausted", "budget_exceeded"}

    @budget_exhausted.inplace.expression
    @classmethod
    def _budget_exhausted_expression(cls):
        return cls.budget_state.in_(
            ["exhausted", "over_budget", "budget_exhausted", "budget_exceeded"]
        )

    @hybrid_property
    def over_budget(self) -> bool:
        return self.budget_state in {"over_budget", "budget_exceeded", "exceeded"}

    @over_budget.inplace.expression
    @classmethod
    def _over_budget_expression(cls):
        return cls.budget_state.in_(["over_budget", "budget_exceeded", "exceeded"])

    @property
    def budget_status(self) -> str:
        return self.budget_state

    @budget_status.setter
    def budget_status(self, value: str) -> None:
        self.budget_state = value

    error_budget_state = budget_status

    @property
    def error_budget_status(self) -> str:
        return self.budget_state

    @error_budget_status.setter
    def error_budget_status(self, value: str) -> None:
        self.budget_state = value

    slo_status = error_budget_status

    checks: Mapped[list["MonitorCheck"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan"
    )
    incidents: Mapped[list["Incident"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan"
    )
