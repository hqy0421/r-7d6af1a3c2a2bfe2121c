"""SLO naming alias for budget persistence models."""

from app.models.error_budget import *  # noqa: F403
from app.models.error_budget import (  # noqa: F401
    Budget,
    BudgetAlert,
    BudgetConsumption,
    ErrorBudget,
    ErrorBudgetAlert,
    ErrorBudgetConsumption,
)

SLO = ErrorBudget
SLOAlert = ErrorBudgetAlert
SLOConsumption = ErrorBudgetConsumption

__all__ = [
    "Budget",
    "BudgetAlert",
    "BudgetConsumption",
    "ErrorBudget",
    "ErrorBudgetAlert",
    "ErrorBudgetConsumption",
    "SLO",
    "SLOAlert",
    "SLOConsumption",
]
