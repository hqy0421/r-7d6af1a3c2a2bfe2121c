"""SLA naming alias for the error-budget service."""

from app.services.error_budget import *  # noqa: F403
from app.services.error_budget import (  # noqa: F401
    calculate_error_budget as calculate_sla,
    evaluate_budget as evaluate_sla,
    get_error_budget as get_sla,
)
