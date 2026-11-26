"""ORM models.

    User ──< Monitor ──< MonitorCheck
         │           └──< Incident
         ├──< NotificationChannel
         └──< StatusPage
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
from app.models.incident import Incident, IncidentStatus
from app.models.monitor import Monitor, MonitorStatus
from app.models.monitor_check import CheckOutcome, MonitorCheck
from app.models.notification_channel import ChannelType, NotificationChannel
from app.models.sla import SLA, SLAAlert, SLAConsumption
from app.models.slo import SLO, SLOAlert, SLOConsumption
from app.models.status_page import StatusPage
from app.models.user import User

__all__ = [
    "BudgetAlert",
    "Budget",
    "BudgetBurn",
    "BudgetConsumption",
    "BudgetConsumptionRecord",
    "BudgetRecord",
    "BudgetRollup",
    "BudgetSummary",
    "ChannelType",
    "CheckOutcome",
    "ErrorBudget",
    "ErrorBudgetAlert",
    "ErrorBudgetBurn",
    "ErrorBudgetConsumption",
    "ErrorBudgetConsumptionRecord",
    "ErrorBudgetRecord",
    "ErrorBudgetRollup",
    "ErrorBudgetSummary",
    "Incident",
    "IncidentStatus",
    "Monitor",
    "MonitorCheck",
    "MonitorStatus",
    "NotificationChannel",
    "SLA",
    "SLAAlert",
    "SLAConsumption",
    "SLO",
    "SLOAlert",
    "SLOConsumption",
    "StatusPage",
    "User",
]
