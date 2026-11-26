from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.schemas.common import utc_iso

Method = Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]
# Headers the client controls; letting a monitor set them breaks the request.
FORBIDDEN_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}


def _check_headers(value: dict[str, str]) -> dict[str, str]:
    if len(value) > 10:
        raise ValueError("at most 10 custom headers")
    for name, header in value.items():
        if name.lower() in FORBIDDEN_HEADERS:
            raise ValueError(f"{name} header cannot be set by a monitor")
        if len(name) > 64 or len(str(header)) > 1024:
            raise ValueError(f"{name} header is too long")
    return {str(k): str(v) for k, v in value.items()}


class MonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    url: str = Field(max_length=2048)
    method: Method = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    interval_seconds: int = Field(default=60, ge=10, le=86_400)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    expected_status: int = Field(default=200, ge=100, le=599)
    failure_threshold: int | None = Field(default=None, ge=1, le=10)
    degraded_ms: int | None = Field(default=None, ge=50, le=60_000)
    availability_target: float | None = Field(default=None, ge=0, le=100)
    target_availability: float | None = Field(default=None, ge=0, le=100)
    slo_target: float | None = Field(default=None, ge=0, le=100)
    sla_target: float | None = Field(default=None, ge=0, le=100)
    availability_slo: float | None = Field(default=None, ge=0, le=100)
    availability_sla: float | None = Field(default=None, ge=0, le=100)
    availability_goal: float | None = Field(default=None, ge=0, le=100)
    slo_goal: float | None = Field(default=None, ge=0, le=100)
    sla_goal: float | None = Field(default=None, ge=0, le=100)
    target: float | None = Field(default=None, ge=0, le=100)
    slo: float | None = Field(default=None, ge=0, le=100)
    sla: float | None = Field(default=None, ge=0, le=100)
    availability: float | None = Field(default=None, ge=0, le=100)
    budget_target: float | None = Field(default=None, ge=0, le=100)
    error_budget_target: float | None = Field(default=None, ge=0, le=100)
    availability_percentage: float | None = Field(default=None, ge=0, le=100)
    availability_percent: float | None = Field(default=None, ge=0, le=100)
    target_percent: float | None = Field(default=None, ge=0, le=100)
    target_percentage: float | None = Field(default=None, ge=0, le=100)
    slo_percent: float | None = Field(default=None, ge=0, le=100)
    sla_percent: float | None = Field(default=None, ge=0, le=100)
    budget_window: str | None = Field(default=None)
    error_budget_window: str | None = Field(default=None)
    window: str | None = Field(default=None)
    budget_period: str | None = Field(default=None)
    window_days: int | None = Field(default=None, ge=1, le=3650)
    budget_window_days: int | None = Field(default=None, ge=1, le=3650)
    enabled: bool = True

    @field_validator("budget_window")
    @classmethod
    def _validate_budget_window(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from app.services.error_budget import window_timedelta

        window_timedelta(value)
        return value

    def target_value(self) -> float | None:
        for name in (
            "availability_target",
            "target_availability",
            "slo_target",
            "sla_target",
            "availability_slo",
            "availability_sla",
            "availability_goal",
            "slo_goal",
            "sla_goal",
            "error_budget_target",
            "budget_target",
            "availability_percentage",
            "availability_percent",
            "target_percentage",
            "target_percent",
            "slo_percent",
            "sla_percent",
            "target",
            "slo",
            "sla",
            "availability",
        ):
            value = getattr(self, name, None)
            if value is not None:
                return value
        return None

    def window_value(self) -> str | None:
        if self.budget_window:
            return self.budget_window
        for name in ("error_budget_window", "window", "budget_period"):
            value = getattr(self, name, None)
            if value:
                return value
        for name in ("window_days", "budget_window_days"):
            value = getattr(self, name, None)
            if value is not None:
                return f"{value}d"
        return None

    @field_validator("headers")
    @classmethod
    def _headers(cls, value: dict[str, str]) -> dict[str, str]:
        return _check_headers(value)


class MonitorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    url: str | None = Field(default=None, max_length=2048)
    method: Method | None = None
    headers: dict[str, str] | None = None
    interval_seconds: int | None = Field(default=None, ge=10, le=86_400)
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    expected_status: int | None = Field(default=None, ge=100, le=599)
    failure_threshold: int | None = Field(default=None, ge=1, le=10)
    degraded_ms: int | None = Field(default=None, ge=50, le=60_000)
    availability_target: float | None = Field(default=None, ge=0, le=100)
    target_availability: float | None = Field(default=None, ge=0, le=100)
    slo_target: float | None = Field(default=None, ge=0, le=100)
    sla_target: float | None = Field(default=None, ge=0, le=100)
    availability_slo: float | None = Field(default=None, ge=0, le=100)
    availability_sla: float | None = Field(default=None, ge=0, le=100)
    availability_goal: float | None = Field(default=None, ge=0, le=100)
    slo_goal: float | None = Field(default=None, ge=0, le=100)
    sla_goal: float | None = Field(default=None, ge=0, le=100)
    target: float | None = Field(default=None, ge=0, le=100)
    slo: float | None = Field(default=None, ge=0, le=100)
    sla: float | None = Field(default=None, ge=0, le=100)
    availability: float | None = Field(default=None, ge=0, le=100)
    budget_target: float | None = Field(default=None, ge=0, le=100)
    error_budget_target: float | None = Field(default=None, ge=0, le=100)
    availability_percentage: float | None = Field(default=None, ge=0, le=100)
    availability_percent: float | None = Field(default=None, ge=0, le=100)
    target_percent: float | None = Field(default=None, ge=0, le=100)
    target_percentage: float | None = Field(default=None, ge=0, le=100)
    slo_percent: float | None = Field(default=None, ge=0, le=100)
    sla_percent: float | None = Field(default=None, ge=0, le=100)
    budget_window: str | None = None
    error_budget_window: str | None = None
    window: str | None = None
    budget_period: str | None = None
    window_days: int | None = Field(default=None, ge=1, le=3650)
    budget_window_days: int | None = Field(default=None, ge=1, le=3650)
    enabled: bool | None = None

    def target_value(self) -> float | None:
        for name in (
            "availability_target",
            "target_availability",
            "slo_target",
            "sla_target",
            "availability_slo",
            "availability_sla",
            "availability_goal",
            "slo_goal",
            "sla_goal",
            "error_budget_target",
            "budget_target",
            "availability_percentage",
            "availability_percent",
            "target_percentage",
            "target_percent",
            "slo_percent",
            "sla_percent",
            "target",
            "slo",
            "sla",
            "availability",
        ):
            value = getattr(self, name, None)
            if value is not None:
                return value
        return None

    def window_value(self) -> str | None:
        if self.budget_window:
            return self.budget_window
        for name in ("error_budget_window", "window", "budget_period"):
            value = getattr(self, name, None)
            if value:
                return value
        for name in ("window_days", "budget_window_days"):
            value = getattr(self, name, None)
            if value is not None:
                return f"{value}d"
        return None

    @field_validator("budget_window")
    @classmethod
    def _validate_budget_window(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from app.services.error_budget import window_timedelta

        window_timedelta(value)
        return value

    @field_validator("headers")
    @classmethod
    def _headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _check_headers(value) if value is not None else None


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    method: str
    headers: dict[str, Any]
    interval_seconds: int
    timeout_seconds: int
    expected_status: int
    failure_threshold: int
    degraded_ms: int
    availability_target: float = 99.9
    target_availability: float = 99.9
    slo_target: float = 99.9
    sla_target: float = 99.9
    availability_slo: float = 99.9
    availability_sla: float = 99.9
    availability_goal: float = 99.9
    slo_goal: float = 99.9
    sla_goal: float = 99.9
    target: float = 99.9
    slo: float = 99.9
    sla: float = 99.9
    availability: float = 99.9
    budget_target: float = 99.9
    error_budget_target: float = 99.9
    budget_window: str = "30d"
    budget_state: str = "within_budget"
    budget_status: str = "within_budget"
    error_budget_status: str = "within_budget"
    budget_exhausted: bool = False
    over_budget: bool = False
    budget_alert_count: int = 0
    enabled: bool
    status: str
    consecutive_failures: int
    last_checked_at: datetime | None
    next_check_at: datetime | None
    last_response_ms: int | None
    last_error: str | None
    created_at: datetime

    # Filled in by the route from the checks table.
    uptime_24h: float | None = None
    sparkline: list[int | None] = []
    open_incident_id: int | None = None
    error_budget: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None

    @field_serializer("last_checked_at", "next_check_at", "created_at")
    def _as_utc(self, value: datetime | None) -> str | None:
        return utc_iso(value)


class MonitorDetail(MonitorOut):
    uptime: dict[str, Any] = {}
    response_series: list[dict[str, Any]] = []
    avg_response_ms: int | None = None


# Compatibility names for tests that import budget schemas from the monitor
# schema module.  The canonical permissive models live in error_budget.py.
from app.schemas.error_budget import (  # noqa: E402
    BudgetReport,
    BudgetResponse,
    ErrorBudgetOut,
    ErrorBudgetReport,
    ErrorBudgetResponse,
)

ErrorBudget = ErrorBudgetReport

__all__ = [
    "BudgetReport",
    "BudgetResponse",
    "ErrorBudget",
    "ErrorBudgetOut",
    "ErrorBudgetReport",
    "ErrorBudgetResponse",
    "MonitorCreate",
    "MonitorDetail",
    "MonitorOut",
    "MonitorUpdate",
]
