"""Compatibility module for the budget model.

The implementation lives in :mod:`app.models.error_budget`; this module lets
callers/tests use the shorter ``app.models.budget`` spelling.
"""

from app.models.error_budget import (
    Budget,
    BudgetAlert,
    BudgetBurn,
    BudgetConsumption,
    BudgetConsumptionRecord,
    BudgetRecord,
    BudgetRollup,
    BudgetSummary,
    ErrorBudget,
    ErrorBudgetAlert,
    ErrorBudgetBurn,
    ErrorBudgetConsumption,
    ErrorBudgetConsumptionRecord,
    ErrorBudgetRecord,
    ErrorBudgetRollup,
    ErrorBudgetSummary,
)

__all__ = [
    "BudgetAlert",
    "Budget",
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
