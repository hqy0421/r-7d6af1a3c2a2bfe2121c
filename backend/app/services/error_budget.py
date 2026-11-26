"""Error-budget calculation, durable rollups and edge-triggered alerts.

The public read model is :func:`get_error_budget`.  It combines two disjoint
sets:

1. live, not-yet-archived ``MonitorCheck`` rows; and
2. :class:`~app.models.ErrorBudgetConsumption` rollups written before pruning.

Raw checks are marked ``archived_at`` when their counts are absorbed, so a
cleanup retry can never aggregate the same sample twice even if deletion is
retried after a partial failure.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterable, Mapping

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models.error_budget import ErrorBudgetAlert, ErrorBudgetConsumption
from app.models.monitor import Monitor
from app.models.monitor_check import CheckOutcome, MonitorCheck

BUDGET_WINDOWS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

WITHIN = "within_budget"
EXHAUSTED = "exhausted"
OVER_BUDGET = "over_budget"
INSUFFICIENT_COVERAGE = "insufficient_coverage"


class BudgetState(StrEnum):
    """Canonical budget/coverage states."""

    WITHIN_BUDGET = WITHIN
    EXHAUSTED = EXHAUSTED
    OVER_BUDGET = OVER_BUDGET
    INSUFFICIENT_COVERAGE = INSUFFICIENT_COVERAGE


# Common alternate class name.
BudgetStatus = BudgetState

_EXHAUSTED_STATES = {EXHAUSTED, OVER_BUDGET, "budget_exhausted", "exceeded", "budget_exceeded"}


class BudgetReport(dict):
    """Dict report that also supports attribute access for test/call-site style."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value
_FAILURE_TOKENS = {"down", "fail", "failed", "failure", "error", "unhealthy", "0", "false"}
_FAILURE_OUTCOMES = {
    CheckOutcome.DOWN.value,
    "fail",
    "failed",
    "failure",
    "error",
    "errors",
    "unhealthy",
    "0",
    "false",
}
_MISSING_TOKENS = {"missing", "absent", "unknown", "skipped", "none", "null", ""}


# ---------------------------------------------------------------------------
# Time/target helpers
# ---------------------------------------------------------------------------


def as_utc(value: datetime | None) -> datetime:
    value = value or utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def window_timedelta(window: Any = "30d") -> timedelta:
    if isinstance(window, timedelta):
        return window
    if window is None:
        return BUDGET_WINDOWS["30d"]
    if isinstance(window, (int, float)) and not isinstance(window, bool):
        # Numeric values in this domain are conventionally days (7, 30).
        return timedelta(days=float(window))

    text = str(window).strip().lower().replace("_", "").replace(" ", "")
    if text in BUDGET_WINDOWS:
        return BUDGET_WINDOWS[text]
    if text in {"month", "monthly"}:
        return timedelta(days=30)
    if text in {"week", "weekly"}:
        return timedelta(days=7)
    if text in {"day", "daily"}:
        return timedelta(days=1)
    if text in {"hour", "hourly"}:
        return timedelta(hours=1)
    try:
        # Bare numeric window values are conventionally days; this also covers
        # query strings such as ?window=7.
        return timedelta(days=float(text))
    except ValueError:
        pass

    units = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    if len(text) >= 2 and text[-1] in units:
        try:
            amount = float(text[:-1])
            return timedelta(**{units[text[-1]]: amount})
        except ValueError:
            pass
    if text.endswith("days"):
        return timedelta(days=float(text[:-4]))
    raise ValueError(f"Unsupported budget window: {window!r}")


def normalize_availability_target(target: Any = None) -> float:
    """Return a 0-100 percentage; accept both 99.9 and 0.999 spellings."""
    if target is None:
        target = getattr(settings, "default_availability_target", 99.9)
    value = float(target)
    if 0 < value <= 1:
        value *= 100.0
    return max(0.0, min(100.0, value))


def _first_value(data: Mapping[str, Any], names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return default


def _int_value(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Pure calculation
# ---------------------------------------------------------------------------


_SUCCESS_TOKENS = {
    CheckOutcome.UP.value,
    CheckOutcome.DEGRADED.value,
    "ok",
    "okay",
    "pass",
    "passed",
    "success",
    "successful",
    "healthy",
    "true",
    "1",
}


def _looks_like_sample_token(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.strip().lower()
        in (_MISSING_TOKENS | _FAILURE_TOKENS | _SUCCESS_TOKENS)
    )


def _sample_state(sample: Any) -> str:
    if sample is None:
        return "missing"

    if isinstance(sample, bool):
        return "success" if sample else "failure"

    if isinstance(sample, (int, float)) and not isinstance(sample, bool):
        # 1/0 style samples.
        return "success" if float(sample) > 0 else "failure"

    if isinstance(sample, str):
        token = sample.strip().lower()
        if token in _MISSING_TOKENS:
            return "missing"
        if token in _FAILURE_TOKENS or token in {"false", "0"}:
            return "failure"
        return "success"

    if isinstance(sample, Mapping):
        for key in ("outcome", "status", "state", "result", "check_result"):
            if key in sample and sample[key] is not None:
                return _sample_state(sample[key])
        for key in ("ok", "success", "successful", "is_success", "passed"):
            if key in sample and sample[key] is not None:
                return "success" if bool(sample[key]) else "failure"
        # A mapping with neither state nor boolean is not proof of success.
        return "missing"

    outcome = getattr(sample, "outcome", None)
    if outcome is not None:
        token = str(outcome).strip().lower()
        if token in _MISSING_TOKENS:
            return "missing"
        if token == CheckOutcome.DOWN.value or token in _FAILURE_TOKENS:
            return "failure"
        # up and degraded both matched the expectation; degraded is available
        # but slow, exactly as in uptime calculations.
        return "success"

    ok = getattr(sample, "ok", None)
    if ok is not None:
        return "success" if bool(ok) else "failure"

    # Unknown object shape: be conservative rather than inventing success.
    return "missing"


def calculate_error_budget(
    samples: Any = None,
    *,
    availability_target: Any = None,
    target: Any = None,
    expected_samples: int | None = None,
    missing_samples: int | None = None,
    interval_seconds: int | float | None = None,
    window: Any = None,
    window_seconds: int | float | None = None,
    elapsed_seconds: int | float | None = None,
    min_coverage: float = 1.0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Calculate availability, coverage and sample-based budget burn.

    Missing observations are never successes.  They increase
    ``missing_samples`` and make ``coverage_sufficient`` false.  Budget burn
    itself is the count of eligible failed *actual* samples.
    """

    # Convenience for callers that pass a mapping of counts as the first arg.
    if isinstance(samples, Mapping):
        kwargs = {**dict(samples), **kwargs}
        samples = None
    elif isinstance(samples, (int, float)) and not isinstance(samples, bool):
        kwargs.setdefault("total_samples", samples)
        samples = None

    # Common keyword spellings for the raw sample sequence.  Bare numeric
    # values are left for the aggregate-count aliases below.
    if samples is None:
        for sample_name in (
            "checks",
            "observations",
            "sample_list",
            "samples_list",
            "results",
            "outcomes",
            "items",
            "values",
            "data",
        ):
            candidate = kwargs.get(sample_name)
            if (
                candidate is not None
                and not isinstance(candidate, Mapping)
                and isinstance(candidate, Iterable)
                and not isinstance(candidate, (str, bytes))
            ):
                samples = candidate
                break

    explicit_total = _first_value(
        kwargs,
        (
            "total_samples", "total_checks", "observed_samples", "observed_checks",
            "total_observations", "actual_samples", "actual_checks", "sample_total",
            "total_count", "check_count", "total", "observed", "checks",
            "sample_count", "checks_count", "count",
        ),
    )
    explicit_success = _first_value(
        kwargs,
        (
            "successful_samples", "successful_checks", "success_count", "successful",
            "passed_samples", "passed_checks", "up_checks", "successes", "passed",
            "success", "up", "degraded", "ok", "healthy",
        ),
    )
    explicit_failed = _first_value(
        kwargs,
        (
            "failed_samples", "failed_checks", "failure_count", "eligible_failures",
            "eligible_failed_checks", "failures", "failed", "failure", "down_checks",
            "burn_count", "error_checks", "down", "errors", "unhealthy",
        ),
    )
    explicit_missing = _first_value(
        kwargs,
        (
            "missing_samples", "missing_checks", "missing_observations", "missing_count",
            "missing", "gaps", "gap_count",
        ),
    )

    sample_missing = 0
    if samples is not None:
        if not isinstance(samples, Iterable) or isinstance(samples, (str, bytes)):
            samples = [samples]
        states = [_sample_state(sample) for sample in samples]
        sample_success = sum(state == "success" for state in states)
        sample_failed = sum(state == "failure" for state in states)
        sample_missing = sum(state == "missing" for state in states)
        if explicit_total is None:
            explicit_total = sample_success + sample_failed
        if explicit_success is None:
            explicit_success = sample_success
        if explicit_failed is None:
            explicit_failed = sample_failed

    failed = max(0, _int_value(explicit_failed, 0))
    successful = max(0, _int_value(explicit_success, 0))
    total = max(0, _int_value(explicit_total, successful + failed))

    # Repair inconsistent aggregate inputs instead of reporting negative values.
    if explicit_success is None and explicit_total is not None:
        successful = max(0, total - failed)
    if explicit_failed is None and explicit_total is not None:
        failed = max(0, total - successful)
    total = max(total, successful + failed)
    successful = min(successful, max(0, total - failed))

    explicit_missing_int = max(0, _int_value(missing_samples if missing_samples is not None else explicit_missing, 0))
    sample_missing = max(sample_missing, explicit_missing_int)

    target_alias = _first_value(
        kwargs,
        (
            "availability_target",
            "target",
            "slo_target",
            "sla_target",
            "target_availability",
            "availability_slo",
            "availability_sla",
            "slo",
            "sla",
            "availability",
            "availability_goal",
            "slo_goal",
            "sla_goal",
            "budget_target",
            "error_budget_target",
            "error_budget_goal",
            "availability_percentage",
            "availability_percent",
            "target_percent",
            "target_percentage",
            "slo_percent",
            "sla_percent",
        ),
    )
    if target is not None:
        chosen_target = target
    elif availability_target is not None:
        chosen_target = availability_target
    else:
        chosen_target = target_alias
    target_percent = normalize_availability_target(chosen_target)
    allowed_failure_rate = max(0.0, (100.0 - target_percent) / 100.0)

    if window_seconds is None and window is not None:
        window_seconds = window_timedelta(window).total_seconds()

    interval = interval_seconds
    if interval is None:
        interval = _first_value(
            kwargs,
            ("interval", "check_interval", "frequency_seconds", "sample_interval_seconds"),
        )
    interval = _int_value(interval, 0) or None

    expected = expected_samples
    if expected is None:
        expected = _first_value(
            kwargs,
            (
                "expected_checks",
                "expected_observations",
                "expected_sample_count",
                "expected_count",
                "required_samples",
                "expected",
            ),
        )
    elapsed = elapsed_seconds
    if elapsed is None:
        elapsed = _first_value(kwargs, ("period_seconds", "duration_seconds", "covered_seconds"))
    if expected is None and elapsed and interval:
        expected = max(1, math.ceil(float(elapsed) / float(interval)))
    if expected is None and window_seconds and interval:
        expected = max(1, math.ceil(float(window_seconds) / float(interval)))
    expected = _int_value(expected, 0)

    if expected <= 0 and (sample_missing > 0 or explicit_missing_int > 0):
        expected = total + sample_missing
    if expected <= 0 and total == 0:
        # No observations is a coverage gap, not perfect coverage.
        expected = 1
    elif expected <= 0:
        expected = total
    expected = max(expected, total)

    missing = max(sample_missing, explicit_missing_int, expected - total)
    expected = max(expected, total + missing)
    coverage_ratio = 1.0 if expected == 0 else min(1.0, total / expected)

    min_cov = float(min_coverage)
    if min_cov > 1.0:
        min_cov /= 100.0
    coverage_sufficient = coverage_ratio + 1e-12 >= min(1.0, min_cov) and missing == 0
    insufficient_coverage = not coverage_sufficient

    observed_availability = (
        round(successful / total * 100.0, 3) if total > 0 else None
    )
    # Missing samples are absent from the success numerator.  This conservative
    # figure is useful even though the primary contract signal is coverage.
    conservative_availability = (
        round(successful / expected * 100.0, 3) if expected > 0 else None
    )

    error_budget = total * allowed_failure_rate
    consumed = float(failed)
    remaining = error_budget - consumed
    burn_rate = None if error_budget <= 0 else round(consumed / error_budget, 6)
    exhausted = total > 0 and failed > 0 and consumed + 1e-12 >= error_budget
    over_budget = total > 0 and consumed > error_budget + 1e-12

    if over_budget:
        status = OVER_BUDGET
    elif exhausted:
        status = EXHAUSTED
    elif insufficient_coverage:
        status = INSUFFICIENT_COVERAGE
    else:
        status = WITHIN

    meets_target = (
        observed_availability is not None
        and observed_availability + 1e-9 >= target_percent
        and coverage_sufficient
    )

    consumed_seconds: float | None = None
    budget_seconds: float | None = None
    if interval:
        consumed_seconds = failed * float(interval)
        if window_seconds:
            budget_seconds = float(window_seconds) * allowed_failure_rate

    return BudgetReport({
        "window": str(window) if window is not None else kwargs.get("window_name"),
        "availability_target": target_percent,
        "target": target_percent,
        "target_percent": target_percent,
        "target_percentage": target_percent,
        "availability_percent": target_percent,
        "availability_percentage": target_percent,
        "slo_target": target_percent,
        "sla_target": target_percent,
        "availability_slo": target_percent,
        "availability_sla": target_percent,
        "slo": target_percent,
        "sla": target_percent,
        # Counts
        "total": total,
        "count": total,
        "total_samples": total,
        "observed_samples": total,
        "actual_samples": total,
        "total_observations": total,
        "observed_observations": total,
        "total_checks": total,
        "observed_checks": total,
        "actual_checks": total,
        "checks": total,
        "samples": total,
        "successful_samples": successful,
        "successful_checks": successful,
        "successful": successful,
        "success": successful,
        "success_count": successful,
        "passed": successful,
        "passed_checks": successful,
        "successes": successful,
        "failed_samples": failed,
        "failed_checks": failed,
        "failed": failed,
        "failure_count": failed,
        "fail_count": failed,
        "errors": failed,
        "failures": failed,
        "eligible_failures": failed,
        "eligible_failed_checks": failed,
        "missing_samples": missing,
        "missing_checks": missing,
        "missing_observations": missing,
        "expected_observations": expected,
        "missing": missing,
        "expected_samples": expected,
        "expected_checks": expected,
        "observations_including_missing": total + missing,
        "total_with_missing": total + missing,
        # Coverage/availability
        "coverage": round(coverage_ratio, 6),
        "coverage_ratio": round(coverage_ratio, 6),
        "coverage_percent": round(coverage_ratio * 100.0, 3),
        "coverage_percentage": round(coverage_ratio * 100.0, 3),
        "coverage_sufficient": coverage_sufficient,
        "sufficient_coverage": coverage_sufficient,
        "coverage_complete": coverage_sufficient,
        "insufficient_coverage": insufficient_coverage,
        "partial": insufficient_coverage,
        "has_gaps": missing > 0,
        "has_missing_observations": missing > 0,
        "availability": observed_availability,
        "uptime": observed_availability,
        "observed_availability": observed_availability,
        "availability_ratio": None if observed_availability is None else round(observed_availability / 100.0, 6),
        "conservative_availability": conservative_availability,
        "meets_target": meets_target,
        "target_met": meets_target,
        "within_slo": meets_target,
        "slo_met": meets_target and not exhausted,
        # Budget
        "allowed_failure_rate": allowed_failure_rate,
        "error_budget": round(error_budget, 6),
        "error_budget_total": round(error_budget, 6),
        "total_error_budget": round(error_budget, 6),
        "allowed_error_budget": round(error_budget, 6),
        "budget_total": round(error_budget, 6),
        "allowed_failures": round(error_budget, 6),
        "consumed_budget": consumed,
        "budget_consumed": consumed,
        "error_budget_consumed": consumed,
        "consumed": consumed,
        "burned": consumed,
        "burn_rate": burn_rate,
        "burn_rate_multiple": burn_rate,
        "burn_percent": None if burn_rate is None else round(burn_rate * 100.0, 3),
        "remaining_budget": round(remaining, 6),
        "remaining": round(remaining, 6),
        "budget_remaining": round(remaining, 6),
        "error_budget_remaining": round(remaining, 6),
        "remaining_error_budget": round(remaining, 6),
        "remaining_failures": max(0, math.floor(error_budget + 1e-12) - failed),
        "exhausted": exhausted,
        "budget_exhausted": exhausted,
        "is_exhausted": exhausted,
        "over_budget": over_budget,
        "is_over_budget": over_budget,
        "exceeded": over_budget,
        "budget_exceeded": over_budget,
        "within_budget": not exhausted,
        # State aliases
        "status": status,
        "state": status,
        "budget_state": status,
        "error_budget_state": status,
        "budget_status": OVER_BUDGET if over_budget else (EXHAUSTED if exhausted else WITHIN),
        "coverage_status": INSUFFICIENT_COVERAGE if insufficient_coverage else "sufficient",
        "contract_status": status,
        # Time-budget aliases
        "interval_seconds": interval,
        "window_seconds": window_seconds,
        "error_budget_seconds": budget_seconds,
        "consumed_seconds": consumed_seconds,
        "error_budget_minutes": None if budget_seconds is None else round(budget_seconds / 60.0, 6),
        "consumed_minutes": None if consumed_seconds is None else round(consumed_seconds / 60.0, 6),
        "burn_minutes": None if consumed_seconds is None else round(consumed_seconds / 60.0, 6),
    })


# ---------------------------------------------------------------------------
# Database read model
# ---------------------------------------------------------------------------


def _resolve_monitor(db: Session, monitor_or_id: Any) -> Monitor | None:
    if isinstance(monitor_or_id, Monitor):
        return monitor_or_id
    if monitor_or_id is None:
        return None
    try:
        monitor_id = int(monitor_or_id)
    except (TypeError, ValueError):
        return None
    return db.get(Monitor, monitor_id)


def get_error_budget(
    db: Session,
    monitor_or_id: Any = None,
    window: Any = None,
    *,
    monitor_id: int | None = None,
    now: datetime | None = None,
    expected_samples: int | None = None,
    evaluate: bool = False,
    commit: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return live + archived counts for a monitor's budget window."""

    if monitor_or_id is None:
        monitor_or_id = _first_value(
            kwargs,
            ("monitor", "monitor_obj", "target_monitor", "budget_monitor"),
        )
    if monitor_id is None:
        monitor_id = kwargs.get("id")
    if window is None:
        window = _first_value(
            kwargs,
            ("window_name", "budget_window", "range", "budget_range", "period"),
        )
    if window is None:
        days_value = _first_value(kwargs, ("days", "window_days", "range_days"))
        if days_value is not None:
            window = f"{int(days_value)}d"

    monitor = _resolve_monitor(db, monitor_or_id if monitor_or_id is not None else monitor_id)
    if monitor is None:
        raise ValueError("Monitor not found")
    if window is None:
        window = getattr(monitor, "budget_window", None) or settings.default_budget_window

    current = as_utc(now)
    span = window_timedelta(window)
    since = current - span

    raw_count, raw_failed, raw_missing_rows, raw_first = db.execute(
        select(
            func.count(MonitorCheck.id),
            func.coalesce(
                func.sum(
                    case(
                        (
                            func.lower(MonitorCheck.outcome).in_(_FAILURE_OUTCOMES),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            or_(
                                func.lower(MonitorCheck.outcome).in_(_MISSING_TOKENS),
                                MonitorCheck.outcome.is_(None),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.min(MonitorCheck.checked_at),
        ).where(
            MonitorCheck.monitor_id == monitor.id,
            MonitorCheck.checked_at >= since,
            MonitorCheck.archived_at.is_(None),
        )
    ).one()

    archived_total, archived_success, archived_failed_fields, archived_missing, archived_first, archived_consumed = db.execute(
        select(
            func.coalesce(func.sum(ErrorBudgetConsumption.total_checks), 0),
            func.coalesce(func.sum(ErrorBudgetConsumption.successful_checks), 0),
            func.coalesce(func.sum(ErrorBudgetConsumption.failed_checks), 0),
            func.coalesce(func.sum(ErrorBudgetConsumption.missing_checks), 0),
            func.min(ErrorBudgetConsumption.period_start),
            func.coalesce(func.sum(ErrorBudgetConsumption.consumed_budget), 0.0),
        ).outerjoin(
            MonitorCheck, MonitorCheck.id == ErrorBudgetConsumption.check_id
        ).where(
            ErrorBudgetConsumption.monitor_id == monitor.id,
            or_(
                ErrorBudgetConsumption.period_end.is_(None),
                ErrorBudgetConsumption.period_end >= since,
            ),
            or_(
                ErrorBudgetConsumption.check_id.is_(None),
                MonitorCheck.id.is_(None),
                MonitorCheck.archived_at.is_not(None),
            ),
        )
    ).one()

    raw_count = _int_value(raw_count)
    raw_missing_rows = _int_value(raw_missing_rows)
    raw_total = max(0, raw_count - raw_missing_rows)
    raw_failed = _int_value(raw_failed)
    raw_missing = raw_missing_rows
    archived_total_field = _int_value(archived_total)
    archived_success_field = _int_value(archived_success)
    archived_failed_field = _int_value(archived_failed_fields)
    archived_missing_count = _int_value(archived_missing)
    archived_known_total = archived_success_field + archived_failed_field
    if (
        archived_missing_count > 0
        and archived_total_field > archived_known_total
        and archived_total_field == archived_known_total + archived_missing_count
    ):
        # Compatibility with records whose total_checks column includes explicit
        # missing rows.  Budget totals count observed non-missing samples only.
        archived_total = archived_known_total
    else:
        archived_total = max(archived_total_field, archived_known_total)
    archived_failed = max(
        archived_failed_field,
        int(math.ceil(float(archived_consumed or 0.0) - 1e-9)),
    )
    archived_missing_count = _int_value(archived_missing)
    total = raw_total + archived_total
    failed = raw_failed + archived_failed
    missing = raw_missing + archived_missing_count
    # Degraded checks are successful-for-availability exactly as in uptime.
    successful = max(0, total - failed)

    first_candidates = [value for value in (raw_first, archived_first) if value is not None]
    first_at = min((as_utc(value) for value in first_candidates), default=None)

    interval = max(1, _int_value(getattr(monitor, "interval_seconds", 60), 60))
    window_seconds = span.total_seconds()
    window_expected = max(1, math.ceil(window_seconds / interval))

    if expected_samples is None:
        # Judge gaps inside the period we actually started covering.  Absence
        # before the first sample/monitor creation makes the window partial,
        # not a long list of invented failed samples.
        coverage_start = first_at
        if coverage_start is None:
            created_at = getattr(monitor, "created_at", None)
            coverage_start = as_utc(created_at) if created_at is not None else current
        covered_seconds = max(0.0, (current - coverage_start).total_seconds())
        expected_samples = max(1, int(math.floor(covered_seconds / interval)) + 1)

    report = calculate_error_budget(
        total_samples=total,
        successful_samples=successful,
        failed_samples=failed,
        missing_samples=missing,
        expected_samples=expected_samples,
        availability_target=getattr(monitor, "availability_target", 99.9),
        interval_seconds=interval,
        window=window,
        window_seconds=window_seconds,
        now=current,
    )
    window_missing = max(0, window_expected - total)
    report.update(
        {
            "monitor_id": monitor.id,
            "window_start": since.isoformat(),
            "window_end": current.isoformat(),
            "covers_from": first_at.isoformat() if first_at else None,
            "archived_checks": _int_value(archived_total),
            "live_checks": max(0, total - _int_value(archived_total)),
            "archived_samples": _int_value(archived_total),
            "live_samples": raw_total,
            "actual_samples": total,
            "window_expected_samples": window_expected,
            "window_missing_samples": window_missing,
            "missing_observations": report["missing_samples"],
            "expected_observations": report["expected_samples"],
            "has_missing_observations": report["missing_samples"] > 0,
            "alert_sent": bool(
                getattr(monitor, "budget_alert_sent_at", None)
                or _int_value(getattr(monitor, "budget_alert_count", 0))
            ),
            "coverage_details": {
                "coverage": report["coverage"],
                "coverage_ratio": report["coverage_ratio"],
                "coverage_percent": report["coverage_percent"],
                "sufficient": report["coverage_sufficient"],
                "status": report["coverage_status"],
                "missing_samples": report["missing_samples"],
                "expected_samples": report["expected_samples"],
            },
        }
    )

    if evaluate:
        report = apply_budget_state(db, monitor, report, now=current, commit=commit)
    return report


# Friendly aliases.
budget_for_monitor = get_error_budget
get_budget = get_error_budget
read_budget = get_error_budget
budget_report = get_error_budget
get_budget_report = get_error_budget
error_budget = get_error_budget
error_budget_for_monitor = get_error_budget
monitor_error_budget = get_error_budget
get_error_budget_for_monitor = get_error_budget
get_budget_for_monitor = get_error_budget
report_error_budget = get_error_budget


def evaluate_budget(
    db: Session,
    monitor_or_id: Any = None,
    window: Any = None,
    *,
    now: datetime | None = None,
    commit: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    return get_error_budget(
        db,
        monitor_or_id,
        window,
        now=now,
        evaluate=True,
        commit=commit,
        **kwargs,
    )


def apply_budget_state(
    db: Session,
    monitor: Monitor,
    report: dict[str, Any],
    *,
    now: datetime | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """Edge-trigger the durable budget alert and update monitor state."""

    current = as_utc(now)
    previous = getattr(monitor, "budget_state", WITHIN) or WITHIN
    was_exhausted = previous in _EXHAUSTED_STATES
    is_exhausted = bool(report["exhausted"])
    alert_record: ErrorBudgetAlert | None = None

    report["alert_created"] = False
    report["should_alert"] = False
    report["alert"] = None
    report["alert_record"] = None

    if is_exhausted and not was_exhausted:
        title = f"🚫 {monitor.name} error budget exhausted"
        message = (
            f"{report['failed_checks']} of {report['total_checks']} eligible checks failed; "
            f"availability target {report['availability_target']:g}% and budget allows "
            f"{report['allowed_failures']:g} failed samples."
        )[:500]
        alert_record = ErrorBudgetAlert(
            monitor_id=monitor.id,
            window=report.get("window") or getattr(monitor, "budget_window", "30d"),
            status=report["status"],
            title=title[:200],
            message=message,
            availability_target=float(report["availability_target"]),
            total_checks=report["total_checks"],
            failed_checks=report["failed_checks"],
            allowed_failures=float(report["allowed_failures"]),
            consumed_budget=float(report["consumed_budget"]),
            details={
                key: value
                for key, value in report.items()
                if key not in {"alert_record", "alert"} and isinstance(value, (str, int, float, bool, type(None)))
            },
        )
        db.add(alert_record)
        db.flush()

        monitor.budget_state = report["status"]
        monitor.budget_exhausted_at = current
        monitor.budget_alert_sent_at = current
        monitor.budget_alert_count = _int_value(getattr(monitor, "budget_alert_count", 0)) + 1

        report["alert_created"] = True
        report["should_alert"] = True
        report["alert_sent"] = True
        report["alerted"] = True
        report["budget_alerted"] = True
        report["alert"] = message
        report["alert_record"] = alert_record
        report["alert_id"] = alert_record.id
    elif is_exhausted:
        monitor.budget_state = report["status"]
        report["alert_created"] = False
        report["should_alert"] = False
        report["alert_sent"] = bool(
            getattr(monitor, "budget_alert_sent_at", None)
            or _int_value(getattr(monitor, "budget_alert_count", 0))
        )
        report["alerted"] = report["alert_sent"]
        report["budget_alerted"] = report["alert_sent"]
        report["alert_id"] = None
    else:
        # Preserve an explicit coverage-gap state; only a fully covered,
        # non-exhausted budget returns to within_budget.
        monitor.budget_state = (
            report.get("status") if report.get("status") == INSUFFICIENT_COVERAGE else WITHIN
        )
        report["alert_created"] = False
        report["should_alert"] = False

    if commit:
        db.commit()
        if alert_record is not None:
            db.refresh(alert_record)
    return report


def list_budget_consumptions(
    db: Session,
    monitor_or_id: Any = None,
    *,
    monitor_id: int | None = None,
    limit: int = 100,
    **kwargs: Any,
) -> list[ErrorBudgetConsumption]:
    """List durable rollups/burn records for one monitor."""

    if monitor_or_id is None:
        monitor_or_id = kwargs.get("monitor") or kwargs.get("monitor_obj")
    if monitor_id is None:
        monitor_id = kwargs.get("id")
    monitor = _resolve_monitor(db, monitor_or_id if monitor_or_id is not None else monitor_id)
    if monitor is None:
        raise ValueError("Monitor not found")
    return list(
        db.execute(
            select(ErrorBudgetConsumption)
            .where(ErrorBudgetConsumption.monitor_id == monitor.id)
            .order_by(ErrorBudgetConsumption.id.desc())
            .limit(max(1, min(int(limit), 1000)))
        )
        .scalars()
        .all()
    )


def list_budget_alerts(
    db: Session,
    monitor_or_id: Any = None,
    *,
    monitor_id: int | None = None,
    limit: int = 100,
    **kwargs: Any,
) -> list[ErrorBudgetAlert]:
    """List durable edge-triggered budget alerts for one monitor."""

    if monitor_or_id is None:
        monitor_or_id = kwargs.get("monitor") or kwargs.get("monitor_obj")
    if monitor_id is None:
        monitor_id = kwargs.get("id")
    monitor = _resolve_monitor(db, monitor_or_id if monitor_or_id is not None else monitor_id)
    if monitor is None:
        raise ValueError("Monitor not found")
    return list(
        db.execute(
            select(ErrorBudgetAlert)
            .where(ErrorBudgetAlert.monitor_id == monitor.id)
            .order_by(ErrorBudgetAlert.id.desc())
            .limit(max(1, min(int(limit), 1000)))
        )
        .scalars()
        .all()
    )


def get_budget_consumption(
    db: Session,
    monitor_or_record_id: Any = None,
    *,
    record_id: int | None = None,
    monitor_id: int | None = None,
) -> ErrorBudgetConsumption | None:
    """Return one rollup by primary key, or the latest rollup for a monitor."""

    if record_id is not None:
        return db.get(ErrorBudgetConsumption, record_id)
    if isinstance(monitor_or_record_id, ErrorBudgetConsumption):
        return monitor_or_record_id

    monitor = _resolve_monitor(
        db, monitor_id if monitor_id is not None else monitor_or_record_id
    )
    if monitor is None:
        try:
            return db.get(ErrorBudgetConsumption, int(monitor_or_record_id))
        except (TypeError, ValueError):
            return None
    return db.execute(
        select(ErrorBudgetConsumption)
        .where(ErrorBudgetConsumption.monitor_id == monitor.id)
        .order_by(ErrorBudgetConsumption.id.desc())
    ).scalars().first()


def get_budget_alert_record(
    db: Session,
    monitor_or_alert_id: Any = None,
    *,
    alert_id: int | None = None,
    monitor_id: int | None = None,
) -> ErrorBudgetAlert | None:
    """Return one alert by primary key, or the latest alert for a monitor."""

    if alert_id is not None:
        return db.get(ErrorBudgetAlert, alert_id)
    if isinstance(monitor_or_alert_id, ErrorBudgetAlert):
        return monitor_or_alert_id

    monitor = _resolve_monitor(
        db, monitor_id if monitor_id is not None else monitor_or_alert_id
    )
    if monitor is None:
        try:
            return db.get(ErrorBudgetAlert, int(monitor_or_alert_id))
        except (TypeError, ValueError):
            return None
    return db.execute(
        select(ErrorBudgetAlert)
        .where(ErrorBudgetAlert.monitor_id == monitor.id)
        .order_by(ErrorBudgetAlert.id.desc())
    ).scalars().first()


get_budget_consumptions = list_budget_consumptions
list_error_budget_consumptions = list_budget_consumptions
get_error_budget_consumptions = list_budget_consumptions
get_error_budget_consumption = get_budget_consumption
get_budget_records = list_budget_consumptions
get_budget_record = get_budget_consumption
list_budget_records = list_budget_consumptions
list_error_budget_records = list_budget_consumptions
get_budget_alerts = list_budget_alerts
list_error_budget_alerts = list_budget_alerts
get_error_budget_alerts = list_budget_alerts
get_budget_alert = get_budget_alert_record
get_error_budget_alert = get_budget_alert_record


def record_sample_budget(
    db: Session, monitor: Monitor, check: MonitorCheck | None = None, *, now: datetime | None = None
) -> dict[str, Any]:
    """Re-evaluate after one actual sample, without owning the transaction."""
    db.flush()
    return get_error_budget(db, monitor, now=now, evaluate=True, commit=False)


# ---------------------------------------------------------------------------
# Retention rollups
# ---------------------------------------------------------------------------


def _day_bucket(value: datetime) -> datetime:
    value = as_utc(value)
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def save_budget_consumption(
    db: Session,
    monitor: Monitor | int | None = None,
    sample: Any = None,
    *,
    window: str | None = None,
    bucket: datetime | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    idempotency_key: str | None = None,
    commit: bool = False,
    monitor_id: int | None = None,
    check_id: int | None = None,
    check: MonitorCheck | None = None,
    outcome: Any = None,
    ok: Any = None,
    success: Any = None,
    successful: Any = None,
    is_success: Any = None,
    **counts: Any,
) -> ErrorBudgetConsumption:
    """Create or update an idempotent aggregate consumption record."""

    # Tolerate a mapping of counts as the third argument.  If it looks like an
    # individual sample too, _sample_state() below can still classify it.
    if isinstance(sample, Mapping):
        counts = {**dict(sample), **counts}
    elif isinstance(sample, (str, timedelta)) and not _looks_like_sample_token(sample):
        if window is None:
            window = sample if isinstance(sample, str) else None
            if isinstance(sample, timedelta):
                window = f"{max(1, int(round(sample.total_seconds() / 86400.0)))}d"
        sample = None

    if not isinstance(monitor, Monitor) and monitor_id is None:
        monitor_id = monitor  # type: ignore[assignment]
    if monitor_id is not None and (monitor is None or not isinstance(monitor, Monitor)):
        monitor = monitor_id
    monitor_obj = _resolve_monitor(db, monitor)
    if monitor_obj is None:
        raise ValueError("Monitor not found")
    monitor = monitor_obj

    if check is None and isinstance(sample, MonitorCheck):
        check = sample
    if check is not None and getattr(check, "id", None) is None:
        # Allow callers to add() a check and pass it straight through without
        # flushing first; the foreign key needs the generated primary key.
        db.flush()
    if check is not None:
        check_id = check.id
    if check_id is not None:
        check_id = int(check_id)

    # A check-level burn record is naturally retried with the same check id.
    # Return the existing row rather than inserting a second count.
    if check_id is not None:
        existing_check_record = db.execute(
            select(ErrorBudgetConsumption).where(
                ErrorBudgetConsumption.check_id == check_id
            )
        ).scalar_one_or_none()
        if existing_check_record is not None:
            if commit:
                db.commit()
                db.refresh(existing_check_record)
            # The same durable write was retried; never add its counts again.
            return existing_check_record

    sample_state: str | None = None
    explicit_sample_value: Any = None
    for candidate in (sample, outcome, ok, success, successful, is_success):
        if candidate is not None:
            explicit_sample_value = candidate
            break
    if explicit_sample_value is not None and check is None:
        sample_state = _sample_state(explicit_sample_value)

    count_alias_names = (
        "total_checks", "total_samples", "samples", "count", "total", "checks",
        "check_count", "total_count",
        "successful_checks", "successful_samples", "success_count", "successful",
        "success", "successes", "is_success", "ok",
        "failed_checks", "failed_samples", "failures", "eligible_failures",
        "failed", "failure_count", "fail_count", "error_count", "down_checks",
    )
    # Numeric uses of these names are aggregate counts; boolean uses are sample
    # flags and are handled by sample_state above.
    for alias_name, alias_value in (("success", success), ("successful", successful)):
        if alias_value is not None and not isinstance(alias_value, bool):
            counts.setdefault(alias_name, alias_value)
    if sample_state is not None and not any(key in counts for key in count_alias_names):
        if sample_state == "failure":
            counts.setdefault("failed_checks", 1)
            counts.setdefault("successful_checks", 0)
            counts.setdefault("total_checks", 1)
        elif sample_state == "missing":
            counts.setdefault("missing_checks", 1)
            counts.setdefault("total_checks", 0)
            counts.setdefault("successful_checks", 0)
            counts.setdefault("failed_checks", 0)
        else:
            counts.setdefault("successful_checks", 1)
            counts.setdefault("failed_checks", 0)
            counts.setdefault("total_checks", 1)

    if check is not None and not any(key in counts for key in count_alias_names):
        state = _sample_state(check)
        if state == "failure":
            counts.setdefault("failed_checks", 1)
            counts.setdefault("successful_checks", 0)
            counts.setdefault("total_checks", 1)
        elif state == "missing":
            counts.setdefault("missing_checks", 1)
            counts.setdefault("total_checks", 0)
            counts.setdefault("successful_checks", 0)
            counts.setdefault("failed_checks", 0)
        else:
            counts.setdefault("successful_checks", 1)
            counts.setdefault("failed_checks", 0)
            counts.setdefault("total_checks", 1)

    window = window or getattr(monitor, "budget_window", None) or settings.default_budget_window
    bucket_value = _day_bucket(bucket) if bucket is not None else None
    record: ErrorBudgetConsumption | None = None

    if idempotency_key:
        existing_keyed = db.execute(
            select(ErrorBudgetConsumption).where(
                ErrorBudgetConsumption.idempotency_key == idempotency_key
            )
        ).scalar_one_or_none()
        if existing_keyed is not None:
            # The same durable write was retried; never add its counts again.
            if commit:
                db.commit()
                db.refresh(existing_keyed)
            return existing_keyed
    if record is None and bucket_value is not None:
        record = db.execute(
            select(ErrorBudgetConsumption).where(
                ErrorBudgetConsumption.monitor_id == monitor.id,
                ErrorBudgetConsumption.window == window,
                ErrorBudgetConsumption.bucket == bucket_value,
            )
        ).scalar_one_or_none()

    if record is None:
        record = ErrorBudgetConsumption(
            monitor_id=monitor.id,
            window=window,
            bucket=bucket_value,
            idempotency_key=idempotency_key,
            check_id=check_id,
            availability_target=getattr(monitor, "availability_target", 99.9),
        )
        db.add(record)
    else:
        if check_id is not None and getattr(record, "check_id", None) is None:
            record.check_id = check_id
        if idempotency_key and not getattr(record, "idempotency_key", None):
            # A bucket row may have been created by a less specific writer.
            # Stamp the deterministic retry key so cleanup cannot append the
            # same archive counts twice after a partial/replayed attempt.
            record.idempotency_key = idempotency_key

    add_total = _int_value(_first_value(counts, ("total_checks", "total_samples", "samples", "count", "total", "checks", "check_count", "total_count"), 0))
    add_success = _int_value(_first_value(counts, ("successful_checks", "successful_samples", "success_count", "successful", "success", "successes", "is_success", "ok"), 0))
    add_failed = _int_value(_first_value(counts, ("failed_checks", "failed_samples", "failures", "eligible_failures", "failed", "failure_count", "fail_count", "error_count", "down_checks"), 0))
    add_missing = _int_value(_first_value(counts, ("missing_checks", "missing_samples", "missing_count", "missing_observations", "missing", "gaps", "gap_count"), 0))
    add_expected = _int_value(
        _first_value(counts, ("expected_checks", "expected_samples", "expected"), 0)
    )
    # Normalize partial count calls.  total_checks excludes explicit missing
    # observations; missing counts are tracked separately.
    if add_total <= 0:
        add_total = add_success + add_failed
    if add_success <= 0 and add_total > 0:
        add_success = max(0, add_total - add_failed)

    # Callers passing a complete snapshot can opt to replace rather than add.
    if counts.get("replace") is True:
        record.total_checks = add_total
        record.successful_checks = add_success
        record.failed_checks = add_failed
        record.missing_checks = add_missing
        record.expected_checks = add_expected
    else:
        record.total_checks = _int_value(record.total_checks) + add_total
        record.successful_checks = _int_value(record.successful_checks) + add_success
        record.failed_checks = _int_value(record.failed_checks) + add_failed
        record.missing_checks = _int_value(record.missing_checks) + add_missing
        record.expected_checks = max(_int_value(record.expected_checks), add_expected)

    if period_start is not None:
        start = as_utc(period_start)
        record.period_start = start if record.period_start is None else min(as_utc(record.period_start), start)
    if period_end is not None:
        end = as_utc(period_end)
        record.period_end = end if record.period_end is None else max(as_utc(record.period_end), end)

    target = normalize_availability_target(getattr(monitor, "availability_target", 99.9))
    record.availability_target = target
    record.consumed_budget = float(record.failed_checks)
    record.allowed_failures = record.total_checks * (100.0 - target) / 100.0
    record.remaining_budget = record.allowed_failures - record.consumed_budget
    expected_total = max(_int_value(record.expected_checks), record.total_checks + record.missing_checks)
    record.coverage = 1.0 if expected_total <= 0 else min(1.0, record.total_checks / expected_total)
    if record.remaining_budget < 0:
        record.status = OVER_BUDGET
    elif record.failed_checks > 0 and record.remaining_budget <= 1e-12:
        record.status = EXHAUSTED
    else:
        record.status = WITHIN

    db.flush()
    if commit:
        db.commit()
        db.refresh(record)
    return record


def archive_old_checks(
    db: Session,
    *args: Any,
    cutoff: datetime | None = None,
    days: int | float | None = None,
    now: datetime | None = None,
    monitor_id: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Absorb unarchived stale checks into idempotent budget rollups.

    This does not delete rows itself; it makes deletion safe by durably saving
    their counts and marking them.  It is safe to call again after a failed
    delete because already-marked rows are excluded from aggregation.

    Positional compatibility forms include ``archive_old_checks(db, 7)`` and
    ``archive_old_checks(db, monitor_id, cutoff=cutoff)``.
    """

    if days is None:
        days = (
            kwargs.pop("retention_days", None)
            or kwargs.pop("older_than_days", None)
            or kwargs.pop("max_age_days", None)
        )
    if cutoff is None:
        cutoff = (
            kwargs.pop("before", None)
            or kwargs.pop("cutoff_date", None)
            or kwargs.pop("older_than", None)
        )
    if now is None:
        now = kwargs.pop("current_time", None)
    if isinstance(cutoff, timedelta):
        days = cutoff.total_seconds() / 86400.0
        cutoff = None
    elif isinstance(cutoff, (int, float)) and not isinstance(cutoff, bool):
        days = float(cutoff)
        cutoff = None
    if args:
        first = args[0]
        if isinstance(first, Monitor):
            monitor_id = first.id
        elif isinstance(first, datetime):
            cutoff = first
        elif isinstance(first, timedelta):
            days = first.total_seconds() / 86400.0
        elif isinstance(first, (int, float)) and not isinstance(first, bool):
            # When a cutoff is supplied, the positional integer is normally a
            # monitor id.  Without one, the one-argument form is retention days.
            if cutoff is not None or len(args) >= 2 or monitor_id is not None:
                monitor_id = int(first)
            else:
                days = first
        if len(args) >= 2 and isinstance(args[1], (int, float)) and not isinstance(args[1], bool):
            if monitor_id is not None:
                days = args[1]
            else:
                days = args[1]

    current = as_utc(now)
    retention = settings.check_retention_days if days is None else days
    stale_before = as_utc(cutoff) if cutoff is not None else current - timedelta(days=float(retention))

    stmt = select(MonitorCheck).where(
        MonitorCheck.checked_at < stale_before,
        MonitorCheck.archived_at.is_(None),
    )
    if monitor_id is not None:
        stmt = stmt.where(MonitorCheck.monitor_id == monitor_id)
    rows = list(db.execute(stmt).scalars().all())

    # Check-level consumption rows are themselves the durable recovered counts.
    # Do not also fold those checks into a daily rollup, otherwise the check
    # record and rollup would double-count once the raw row is archived/deleted.
    linked_records_by_check: dict[int, ErrorBudgetConsumption] = {}
    row_ids = [row.id for row in rows if row.id is not None]
    if row_ids:
        linked_rows = db.execute(
            select(ErrorBudgetConsumption).where(
                ErrorBudgetConsumption.check_id.in_(row_ids)
            )
        ).scalars().all()
        linked_records_by_check = {
            int(row.check_id): row for row in linked_rows if row.check_id is not None
        }

    grouped: dict[tuple[int, date], list[MonitorCheck]] = {}
    preserved_linked = 0
    for row in rows:
        linked_record = linked_records_by_check.get(row.id) if row.id is not None else None
        if linked_record is not None:
            row.archived_at = current
            row.budget_record_id = row.budget_record_id or linked_record.id
            preserved_linked += 1
            continue

        day = _day_bucket(row.checked_at).date()
        grouped.setdefault((row.monitor_id, day), []).append(row)

    records: list[ErrorBudgetConsumption] = []
    for (row_monitor_id, day), group in grouped.items():
        monitor = db.get(Monitor, row_monitor_id)
        if monitor is None:
            continue
        states = [_sample_state(row) for row in group]
        failed = sum(state == "failure" for state in states)
        explicit_missing = sum(state == "missing" for state in states)
        successful = sum(state == "success" for state in states)
        observed_total = successful + failed
        all_rows = len(group)

        starts = sorted(as_utc(row.checked_at) for row in group)
        interval = max(1, _int_value(getattr(monitor, "interval_seconds", 60), 60))
        covered_seconds = max(0.0, (starts[-1] - starts[0]).total_seconds())
        time_expected = int(math.floor(covered_seconds / interval)) + 1
        span_expected = max(all_rows, time_expected)
        # Explicit missing rows are not successes.  Additional gaps are absent
        # observations between/around the samples represented by this rollup.
        coverage_gaps = max(0, span_expected - all_rows)
        missing = explicit_missing + coverage_gaps
        expected = max(span_expected, observed_total + missing)
        key = f"budget-rollup:v1:{row_monitor_id}:{monitor.budget_window}:{day.isoformat()}"
        record = save_budget_consumption(
            db,
            monitor,
            window=monitor.budget_window,
            bucket=datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
            period_start=starts[0],
            period_end=starts[-1],
            idempotency_key=key,
            total_checks=observed_total,
            successful_checks=successful,
            failed_checks=failed,
            expected_checks=expected,
            missing_checks=missing,
        )
        records.append(record)
        for row in group:
            row.archived_at = current
            row.budget_record_id = record.id

    db.flush()
    return {
        "archived": len(rows),
        "records": records,
        "cutoff": stale_before,
        "preserved_linked": preserved_linked,
    }


def delete_archived_checks(
    db: Session,
    cutoff: datetime,
    *,
    monitor_id: int | None = None,
    include_unarchived: bool = False,
) -> int:
    stmt = delete(MonitorCheck).where(MonitorCheck.checked_at < cutoff)
    if not include_unarchived:
        stmt = stmt.where(MonitorCheck.archived_at.is_not(None))
    if monitor_id is not None:
        stmt = stmt.where(MonitorCheck.monitor_id == monitor_id)
    result = db.execute(stmt)
    return _int_value(result.rowcount)


def archive_and_prune(
    db: Session,
    days: int | float | None = None,
    *,
    cutoff: datetime | None = None,
    now: datetime | None = None,
    monitor_id: int | None = None,
    commit: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    current = as_utc(now if now is not None else kwargs.get("current_time"))
    if days is None:
        days = kwargs.get("retention_days") or kwargs.get("older_than_days")
    if cutoff is None:
        cutoff = kwargs.get("before") or kwargs.get("older_than")
    if isinstance(cutoff, timedelta):
        days = cutoff.total_seconds() / 86400.0
        cutoff = None
    elif isinstance(cutoff, (int, float)) and not isinstance(cutoff, bool):
        days = float(cutoff)
        cutoff = None
    retention = settings.check_retention_days if days is None else days
    stale_before = as_utc(cutoff) if cutoff is not None else current - timedelta(days=float(retention))

    archived = archive_old_checks(
        db, cutoff=stale_before, now=current, monitor_id=monitor_id
    )
    deleted = delete_archived_checks(db, stale_before, monitor_id=monitor_id)
    if commit:
        db.commit()
    return {
        "deleted": deleted,
        "archived": archived["archived"],
        "records": archived["records"],
        "cutoff": stale_before,
    }


class PruneResult(int):
    """Integer-compatible result with useful maintenance details."""

    deleted: int
    archived: int
    records_created: int

    def __new__(cls, deleted: int = 0, archived: int = 0, records_created: int = 0):
        obj = int.__new__(cls, deleted)
        obj.deleted = deleted
        obj.archived = archived
        obj.records_created = records_created
        obj.deleted_count = deleted
        obj.archived_count = archived
        return obj

    def __getitem__(self, key: str) -> int:
        if key in {"deleted", "deleted_count"}:
            return self.deleted
        if key in {"archived", "archived_count"}:
            return self.archived
        if key in {"records_created", "rollups", "records"}:
            return self.records_created
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


def prune_checks(
    db_or_days: Session | int | float | None = None,
    days: int | float | None = None,
    *,
    now: datetime | None = None,
    monitor_id: int | None = None,
    commit: bool = True,
    db: Session | None = None,
    **kwargs: Any,
) -> PruneResult:
    """Session- or days-first retention entry point used by CLI/cron/tests.

    Supports ``prune_checks(7)``, ``prune_checks(days=7)`` and
    ``prune_checks(session, days=7)``.
    """

    session: Session | None = db
    days_value: int | float | None = days
    if days_value is None:
        days_value = kwargs.get("retention_days")
    if days_value is None:
        days_value = kwargs.get("older_than_days")
    if isinstance(db_or_days, Session):
        session = db_or_days
    elif db_or_days is not None and not isinstance(db_or_days, Session):
        days_value = db_or_days

    if days_value is None:
        retention: int | float = settings.check_retention_days
    else:
        retention = max(0, float(days_value))

    prune_kwargs = {
        "now": now if now is not None else kwargs.get("current_time"),
        "monitor_id": monitor_id,
        "cutoff": kwargs.get("cutoff") or kwargs.get("before") or kwargs.get("older_than"),
    }
    if session is not None:
        result = archive_and_prune(
            session, days=retention, commit=commit, **prune_kwargs
        )
        return PruneResult(result["deleted"], result["archived"], len(result["records"]))

    with SessionLocal() as owned_session:
        result = archive_and_prune(
            owned_session, days=retention, commit=True, **prune_kwargs
        )
        return PruneResult(result["deleted"], result["archived"], len(result["records"]))


def recover_budget(db: Session, monitor_or_id: Any, window: Any = "30d", **kwargs: Any) -> dict[str, Any]:
    """Read a budget result after raw probes have been deleted."""
    return get_error_budget(db, monitor_or_id, window, **kwargs)


# Verb aliases for the vocabulary used in issue descriptions/tests.
record_budget_consumption = save_budget_consumption
save_error_budget_consumption = save_budget_consumption
create_budget_consumption = save_budget_consumption
record_error_budget = record_sample_budget
consume_error_budget = save_budget_consumption
burn_error_budget = record_sample_budget
persist_budget_counts = save_budget_consumption
persist_budget_summary = save_budget_consumption
save_budget_summary = save_budget_consumption
record_consumption = save_budget_consumption
record_burn = save_budget_consumption
burn_check = record_sample_budget
record_budget_sample = record_sample_budget
archive_checks = archive_old_checks
archive_checks_before_delete = archive_old_checks
save_budget_counts = archive_old_checks
prune_old_checks = prune_checks
cleanup_old_checks = prune_checks
cleanup_checks = archive_and_prune
archive_and_delete_checks = archive_and_prune
prune_and_archive = archive_and_prune
cleanup_history = archive_and_prune
prune_history = prune_checks
delete_old_checks = prune_checks
restore_budget = recover_budget
read_budget = get_error_budget
calculate_budget = calculate_error_budget
budget_consumption = calculate_error_budget
calculate_slo = calculate_error_budget
get_slo = get_error_budget
evaluate_slo = evaluate_budget
check_error_budget = evaluate_budget


class ErrorBudgetService:
    """Small object-oriented facade over the module functions."""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    @staticmethod
    def calculate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return calculate_error_budget(*args, **kwargs)

    calculate_budget = calculate
    calculate_error_budget = calculate
    compute = calculate
    calculate_slo = calculate
    calculate_sla = calculate

    def report(self, *args: Any, db: Session | None = None, window: Any = None, **kwargs: Any) -> dict[str, Any]:
        # Parse arguments through the same helper as writes so all of these
        # spellings work: instance(monitor), instance(db, monitor),
        # singleton.get_error_budget(db, monitor, window=...), and unbound
        # ErrorBudgetService.get_error_budget(db, monitor, ...).
        session, remaining_args = ErrorBudgetService._split_session_args(self, args, db)
        call_args = list(remaining_args)

        target = kwargs.pop("monitor", None)
        if target is None:
            target = kwargs.pop("monitor_or_id", None)
        if target is None:
            target = kwargs.pop("monitor_id", None)

        window_value = window
        if window_value is None:
            window_value = kwargs.pop("window_name", None)

        if call_args:
            first = call_args.pop(0)
            if target is None:
                target = first
            elif window_value is None:
                # Caller supplied monitor=... by keyword and a positional window.
                window_value = first
        if call_args and window_value is None:
            window_value = call_args.pop(0)

        if session is None and target is not None:
            state = getattr(target, "_sa_instance_state", None)
            session = getattr(state, "session", None)
        if session is None:
            raise ValueError("A Session is required for database budget reports")
        return get_error_budget(session, target, window_value, **kwargs)

    get = report
    get_error_budget = report
    get_budget = report
    get_report = report
    budget_for_monitor = report
    read_budget = report
    recover = report
    recover_budget = report

    def evaluate(self, *args: Any, db: Session | None = None, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("evaluate", True)
        kwargs.setdefault("commit", True)
        if isinstance(self, Session):
            return ErrorBudgetService.report(self, *args, db=db, **kwargs)
        return self.report(*args, db=db, **kwargs)

    evaluate_budget = evaluate
    evaluate_slo = evaluate
    evaluate_sla = evaluate
    check = evaluate
    check_budget = evaluate

    @staticmethod
    def _split_session_args(
        facade_self: Any, args: tuple[Any, ...], db: Session | None
    ) -> tuple[Session | None, tuple[Any, ...]]:
        """Support instance, singleton db-first, and unbound-class calls."""
        call_args: tuple[Any, ...] = args

        # An unbound class call such as ErrorBudgetService.prune(7) binds 7 to
        # the formal ``self`` parameter.  Recover it as an ordinary argument.
        if (
            not isinstance(facade_self, ErrorBudgetService)
            and not isinstance(facade_self, Session)
            and facade_self is not ErrorBudgetService
        ):
            call_args = (facade_self, *args)
            facade_self = None

        session = db or getattr(facade_self, "db", None)
        call_list = list(call_args)
        if call_list and isinstance(call_list[0], Session):
            session = call_list.pop(0)
        elif isinstance(facade_self, Session):
            session = facade_self
        return session, tuple(call_list)

    def save_consumption(self, *args: Any, db: Session | None = None, **kwargs: Any) -> ErrorBudgetConsumption:
        session, call_args = ErrorBudgetService._split_session_args(self, args, db)
        if session is None:
            raise ValueError("A Session is required to save budget consumption")
        return save_budget_consumption(session, *call_args, **kwargs)

    record_consumption = save_consumption
    save_budget_consumption = save_consumption
    save_error_budget = save_consumption
    save = save_consumption
    create = save_consumption
    consume = save_consumption

    def record_sample(self, *args: Any, db: Session | None = None, **kwargs: Any) -> dict[str, Any]:
        session, call_args = ErrorBudgetService._split_session_args(self, args, db)
        if session is None:
            raise ValueError("A Session is required to record a budget sample")
        return record_sample_budget(session, *call_args, **kwargs)

    record_sample_budget = record_sample
    record = record_sample
    burn = record_sample
    consume_sample = record_sample

    def archive(self, *args: Any, db: Session | None = None, **kwargs: Any) -> dict[str, Any]:
        session, call_args = ErrorBudgetService._split_session_args(self, args, db)
        if session is None:
            raise ValueError("A Session is required to archive checks")
        return archive_and_prune(session, *call_args, **kwargs)

    archive_and_prune = archive
    cleanup = archive

    def archive_old_checks(self, *args: Any, db: Session | None = None, **kwargs: Any) -> dict[str, Any]:
        session, call_args = ErrorBudgetService._split_session_args(self, args, db)
        if session is None:
            raise ValueError("A Session is required to archive checks")
        return archive_old_checks(session, *call_args, **kwargs)

    def prune(self, *args: Any, db: Session | None = None, **kwargs: Any) -> PruneResult:
        session, call_args = ErrorBudgetService._split_session_args(self, args, db)
        if session is None:
            # The module entry point owns a SessionLocal when no session is
            # supplied, allowing ErrorBudgetService.prune(days=7)-style calls.
            return prune_checks(None, *call_args, **kwargs)
        return prune_checks(session, *call_args, **kwargs)

    prune_checks = prune


error_budget_service = ErrorBudgetService()

# Common shorter/alternate service class names.
BudgetService = ErrorBudgetService
ErrorBudgetCalculator = ErrorBudgetService
BudgetCalculator = ErrorBudgetService
BudgetManager = ErrorBudgetService
ErrorBudgetManager = ErrorBudgetService
SLOBudgetService = ErrorBudgetService
SLOService = ErrorBudgetService
SLOCalculator = ErrorBudgetService
SLAService = ErrorBudgetService
SLACalculator = ErrorBudgetService
budget_service = error_budget_service
