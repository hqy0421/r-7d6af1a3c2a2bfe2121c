"""Short alias for :mod:`app.services.error_budget`."""

from app.services.error_budget import *  # noqa: F403
from app.services.error_budget import (  # noqa: F401
    PruneResult,
    apply_budget_state,
    archive_and_prune,
    archive_old_checks,
    budget_report,
    calculate_error_budget,
    error_budget,
    evaluate_budget,
    get_error_budget,
    normalize_availability_target,
    prune_checks,
    recover_budget,
    save_budget_consumption,
    window_timedelta,
)
