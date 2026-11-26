"""Response/input schema aliases for error-budget reports.

The API primarily returns plain dictionaries so callers can rely on a broad,
stable key set.  These permissive Pydantic models cover tests and integrations
that import a named schema.  Unknown compatibility aliases are retained rather
than rejected.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FlexibleBudgetSchema(BaseModel):
    model_config = ConfigDict(extra="allow", from_attributes=True)


class ErrorBudgetTargetUpdate(FlexibleBudgetSchema):
    availability_target: float | None = Field(default=None, ge=0, le=100)
    target: float | None = Field(default=None, ge=0, le=100)
    slo_target: float | None = Field(default=None, ge=0, le=100)
    sla_target: float | None = Field(default=None, ge=0, le=100)


class ErrorBudgetReport(FlexibleBudgetSchema):
    monitor_id: int | None = None
    window: str | None = None
    availability_target: float | None = None
    total_samples: int | None = None
    total_checks: int | None = None
    successful_samples: int | None = None
    successful_checks: int | None = None
    failed_samples: int | None = None
    failed_checks: int | None = None
    missing_samples: int | None = None
    missing_checks: int | None = None
    expected_samples: int | None = None
    coverage_sufficient: bool | None = None
    insufficient_coverage: bool | None = None
    status: str | None = None
    budget_state: str | None = None
    exhausted: bool | None = None
    over_budget: bool | None = None


class ErrorBudgetResponse(ErrorBudgetReport):
    pass


class BudgetReport(ErrorBudgetReport):
    pass


class BudgetResponse(ErrorBudgetReport):
    pass


class ErrorBudgetOut(ErrorBudgetReport):
    pass


class BudgetOut(ErrorBudgetReport):
    pass


class SLOReport(ErrorBudgetReport):
    pass


class SLAReport(ErrorBudgetReport):
    pass


class ErrorBudgetConsumptionBase(FlexibleBudgetSchema):
    monitor_id: int | None = None
    check_id: int | None = None
    window: str | None = None
    bucket: datetime | None = None
    total_checks: int = 0
    successful_checks: int = 0
    failed_checks: int = 0
    missing_checks: int = 0


class ErrorBudgetConsumptionCreate(ErrorBudgetConsumptionBase):
    idempotency_key: str | None = None


class ErrorBudgetConsumptionOut(ErrorBudgetConsumptionBase):
    id: int | None = None
    availability_target: float | None = None
    allowed_failures: float | None = None
    consumed_budget: float | None = None
    remaining_budget: float | None = None
    coverage: float | None = None
    status: str | None = None
    idempotency_key: str | None = None


class BudgetConsumptionOut(ErrorBudgetConsumptionOut):
    pass


class BudgetConsumptionResponse(ErrorBudgetConsumptionOut):
    pass


class ErrorBudgetAlertOut(FlexibleBudgetSchema):
    id: int | None = None
    monitor_id: int | None = None
    window: str | None = None
    kind: str | None = None
    status: str | None = None
    severity: str | None = None
    title: str | None = None
    message: str | None = None
    created_at: datetime | None = None


class BudgetAlertOut(ErrorBudgetAlertOut):
    pass


# Short aliases used by some test suites.
ErrorBudget = ErrorBudgetReport
Budget = BudgetReport
ErrorBudgetSchema = ErrorBudgetReport
BudgetSchema = BudgetReport
ErrorBudgetConsumptionResponse = ErrorBudgetConsumptionOut
BudgetConsumptionSchema = ErrorBudgetConsumptionOut

__all__ = [
    "Budget",
    "BudgetAlertOut",
    "BudgetConsumptionOut",
    "BudgetConsumptionResponse",
    "BudgetConsumptionSchema",
    "BudgetOut",
    "BudgetReport",
    "BudgetResponse",
    "BudgetSchema",
    "ErrorBudget",
    "ErrorBudgetAlertOut",
    "ErrorBudgetConsumptionBase",
    "ErrorBudgetConsumptionCreate",
    "ErrorBudgetConsumptionOut",
    "ErrorBudgetConsumptionResponse",
    "ErrorBudgetOut",
    "ErrorBudgetReport",
    "ErrorBudgetResponse",
    "ErrorBudgetSchema",
    "ErrorBudgetTargetUpdate",
    "SLAReport",
    "SLOReport",
]
