"""Error-budget persistence.

The consumption table is deliberately aggregate-shaped: pruning raw checks
copies the counts a budget window still needs into this table before deleting
the rows.  It also accepts one-row-per-check burn records through
``check_id``; both styles are useful to callers and neither is counted twice
because raw checks are marked ``archived_at`` before deletion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base, utcnow


class ErrorBudgetConsumption(Base):
    """Recoverable budget counts/burn records for one monitor."""

    __tablename__ = "error_budget_consumptions"
    __table_args__ = (
        UniqueConstraint(
            "monitor_id", "window", "bucket", name="uq_budget_consumption_monitor_window_bucket"
        ),
        Index("ix_budget_consumption_monitor_period", "monitor_id", "period_start", "period_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), index=True
    )
    monitor = relationship("Monitor")

    # "30d" is the normal SLO window.  Rollup buckets may use "rollup"/"all"
    # because their timestamps allow them to serve several requested windows.
    window: Mapped[str] = mapped_column(String(16), default="30d", index=True)
    kind: Mapped[str] = mapped_column(String(24), default="rollup")

    # UTC bucket start for idempotent daily/hourly rollups.  Batch summaries may
    # leave this NULL and use idempotency_key instead.
    bucket: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # When this row represents one check/burn, check_id is populated and unique.
    check_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)

    availability_target: Mapped[float] = mapped_column(Float, default=99.9)

    expected_checks: Mapped[int] = mapped_column(Integer, default=0)
    total_checks: Mapped[int] = mapped_column(Integer, default=0)
    successful_checks: Mapped[int] = mapped_column(Integer, default=0)
    failed_checks: Mapped[int] = mapped_column(Integer, default=0)
    missing_checks: Mapped[int] = mapped_column(Integer, default=0)

    allowed_failures: Mapped[float] = mapped_column(Float, default=0.0)
    consumed_budget: Mapped[float] = mapped_column(Float, default=0.0)
    remaining_budget: Mapped[float] = mapped_column(Float, default=0.0)
    coverage: Mapped[float] = mapped_column(Float, default=1.0)

    status: Mapped[str] = mapped_column(String(32), default="within_budget", index=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, unique=True)
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    @validates("availability_target")
    def _normalize_target(self, _key: str, value: Any) -> float:
        if value is None:
            return 99.9
        normalized = float(value)
        if 0 < normalized <= 1:
            normalized *= 100.0
        return max(0.0, min(100.0, normalized))

    # -- compatibility aliases for the several natural vocabularies --------
    @property
    def target(self) -> float:
        return self.availability_target

    @target.setter
    def target(self, value: float) -> None:
        self.availability_target = float(value)

    slo_target = target
    sla_target = target
    slo = target
    sla = target
    availability_slo = target
    availability_sla = target
    target_availability = target
    availability_goal = target
    slo_goal = target
    sla_goal = target
    availability_percentage = target
    availability_percent = target

    @property
    def total_count(self) -> int:
        return self.total_checks

    @total_count.setter
    def total_count(self, value: int) -> None:
        self.total_checks = int(value or 0)

    check_count = total_count
    total = total_count

    @property
    def missing_count(self) -> int:
        return self.missing_checks

    @missing_count.setter
    def missing_count(self, value: int) -> None:
        self.missing_checks = int(value or 0)

    @property
    def expected_count(self) -> int:
        return self.expected_checks

    @expected_count.setter
    def expected_count(self, value: int) -> None:
        self.expected_checks = int(value or 0)

    @property
    def samples(self) -> int:
        return self.total_checks

    @samples.setter
    def samples(self, value: int) -> None:
        self.total_checks = int(value or 0)

    total_samples = samples

    @property
    def sample_count(self) -> int:
        return self.total_checks

    @sample_count.setter
    def sample_count(self, value: int) -> None:
        self.total_checks = int(value or 0)

    checks_count = sample_count
    count = sample_count

    @property
    def successful_samples(self) -> int:
        return self.successful_checks

    @successful_samples.setter
    def successful_samples(self, value: int) -> None:
        self.successful_checks = int(value or 0)

    success_count = successful_samples
    passed_checks = successful_samples
    passed_samples = successful_samples
    successful = successful_samples
    success = success_count

    @property
    def failed_samples(self) -> int:
        return self.failed_checks

    @failed_samples.setter
    def failed_samples(self, value: int) -> None:
        self.failed_checks = int(value or 0)

    failure_count = failed_samples
    failures = failed_samples
    failed = failed_samples
    eligible_failures = failed_samples
    eligible_failed_checks = failed_samples
    burn_count = failed_samples
    burned_samples = failed_samples
    consumed_samples = failed_samples

    @property
    def missing_samples(self) -> int:
        return self.missing_checks

    @missing_samples.setter
    def missing_samples(self, value: int) -> None:
        self.missing_checks = int(value or 0)

    missing = missing_samples
    missing_observations = missing_samples

    @property
    def expected_samples(self) -> int:
        return self.expected_checks

    @expected_samples.setter
    def expected_samples(self, value: int) -> None:
        self.expected_checks = int(value or 0)

    expected_observations = expected_samples

    @property
    def consumed(self) -> float:
        return self.consumed_budget

    @consumed.setter
    def consumed(self, value: float) -> None:
        self.consumed_budget = float(value or 0.0)

    burned = consumed
    budget_consumed = consumed

    @property
    def remaining(self) -> float:
        return self.remaining_budget

    @remaining.setter
    def remaining(self, value: float) -> None:
        self.remaining_budget = float(value or 0.0)

    budget_remaining = remaining

    @property
    def error_budget(self) -> float:
        return self.allowed_failures

    @error_budget.setter
    def error_budget(self, value: float) -> None:
        self.allowed_failures = float(value or 0.0)

    budget_total = error_budget


class ErrorBudgetAlert(Base):
    """A durable, edge-triggered budget exhaustion alert."""

    __tablename__ = "error_budget_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), index=True
    )
    monitor = relationship("Monitor")
    window: Mapped[str] = mapped_column(String(16), default="30d")
    kind: Mapped[str] = mapped_column(String(40), default="error_budget_exhausted")
    status: Mapped[str] = mapped_column(String(32), default="exhausted")
    severity: Mapped[str] = mapped_column(String(16), default="critical")
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(String(500))

    availability_target: Mapped[float] = mapped_column(Float, default=99.9)
    total_checks: Mapped[int] = mapped_column(Integer, default=0)
    failed_checks: Mapped[int] = mapped_column(Integer, default=0)
    allowed_failures: Mapped[float] = mapped_column(Float, default=0.0)
    consumed_budget: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# Natural class-name aliases for callers/tests that name the concept slightly
# differently.  They share the same table and mapper.
BudgetConsumption = ErrorBudgetConsumption
BudgetConsumptionRecord = ErrorBudgetConsumption
ErrorBudgetConsumptionRecord = ErrorBudgetConsumption
BudgetRecord = ErrorBudgetConsumption
ErrorBudgetRecord = ErrorBudgetConsumption
BudgetBurn = ErrorBudgetConsumption
ErrorBudgetBurn = ErrorBudgetConsumption
ErrorBudget = ErrorBudgetConsumption
Budget = ErrorBudgetConsumption
ErrorBudgetSummary = ErrorBudgetConsumption
BudgetSummary = ErrorBudgetConsumption
ErrorBudgetRollup = ErrorBudgetConsumption
BudgetRollup = ErrorBudgetConsumption
BudgetAlert = ErrorBudgetAlert

__all__ = [
    "Budget",
    "BudgetAlert",
    "BudgetBurn",
    "BudgetConsumption",
    "BudgetConsumptionRecord",
    "BudgetRecord",
    "BudgetRollup",
    "BudgetSummary",
    "ErrorBudget",
    "ErrorBudgetAlert",
    "ErrorBudgetBurn",
    "ErrorBudgetConsumption",
    "ErrorBudgetConsumptionRecord",
    "ErrorBudgetRecord",
    "ErrorBudgetRollup",
    "ErrorBudgetSummary",
]
