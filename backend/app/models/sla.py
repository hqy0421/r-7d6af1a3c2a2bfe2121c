"""SLA naming alias for budget persistence models."""

from app.models.error_budget import *  # noqa: F403
from app.models.error_budget import (  # noqa: F401
    Budget,
    BudgetAlert,
    BudgetConsumption,
    ErrorBudget,
    ErrorBudgetAlert,
    ErrorBudgetConsumption,
)

SLA = ErrorBudget
SLAAlert = ErrorBudgetAlert
SLAConsumption = ErrorBudgetConsumption

__all__ = [
    "Budget",
    "BudgetAlert",
    "BudgetConsumption",
    "ErrorBudget",
    "ErrorBudgetAlert",
    "ErrorBudgetConsumption",
    "SLA",
    "SLAAlert",
    "SLAConsumption",
]
