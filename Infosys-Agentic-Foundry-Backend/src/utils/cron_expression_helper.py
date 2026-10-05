# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""Helpers for building, validating, and previewing cron expressions.

The single source of truth for cron-expression validity is `croniter.is_valid`.
A thin wrapper around it lives here so every code path (create endpoint,
update endpoint, validate-cron endpoint, scheduler runner) uses the same
implementation.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from src.config.constants import CronSchedulerConfig
from src.schemas.scheduler_schemas import (
    DayOfWeek,
    Month,
    ScheduleFrequency,
    ScheduleStructured,
)
from telemetry_wrapper import logger as log


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------


def resolve_timezone(timezone_name: Optional[str]) -> ZoneInfo:
    """Resolve a timezone string (or fall back to the configured default).

    Raises:
        ValueError: If the supplied timezone is not a valid IANA name.
    """
    name = (timezone_name or CronSchedulerConfig.DEFAULT_TIMEZONE).strip()
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        log.warning(f"Invalid timezone '{name}': {exc}")
        raise ValueError(f"Unknown timezone: '{name}'") from exc


# ---------------------------------------------------------------------------
# Structured -> raw cron expression
# ---------------------------------------------------------------------------


def _format_minute(minute: Optional[int]) -> str:
    return str(minute) if minute is not None else "0"


def _format_hour(hour: Optional[int]) -> str:
    return str(hour) if hour is not None else "0"


def build_cron_expression(structured: ScheduleStructured) -> str:
    """Convert a `ScheduleStructured` payload into a 5-field cron string.

    Raises:
        ValueError: If the structured payload is missing fields required for
            the chosen frequency.
    """
    try:
        freq = structured.frequency

        if freq == ScheduleFrequency.MINUTELY:
            interval = structured.interval or 1
            return f"*/{interval} * * * *"

        if freq == ScheduleFrequency.HOURLY:
            interval = structured.interval or 1
            minute = _format_minute(structured.minute)
            return f"{minute} */{interval} * * *"

        if freq == ScheduleFrequency.DAILY:
            interval = structured.interval or 1
            minute = _format_minute(structured.minute)
            hour = _format_hour(structured.hour)
            day_part = "*" if interval == 1 else f"*/{interval}"
            return f"{minute} {hour} {day_part} * *"

        if freq == ScheduleFrequency.WEEKLY:
            if not structured.days_of_week:
                raise ValueError("`days_of_week` is required for WEEKLY frequency.")
            minute = _format_minute(structured.minute)
            hour = _format_hour(structured.hour)
            days = ",".join(d.value for d in structured.days_of_week)
            return f"{minute} {hour} * * {days}"

        if freq == ScheduleFrequency.MONTHLY:
            if not structured.days_of_month:
                raise ValueError(
                    "`days_of_month` is required for MONTHLY frequency."
                )
            minute = _format_minute(structured.minute)
            hour = _format_hour(structured.hour)
            days = ",".join(str(d) for d in sorted(set(structured.days_of_month)))
            return f"{minute} {hour} {days} * *"

        if freq == ScheduleFrequency.YEARLY:
            if structured.month is None or structured.day_of_month is None:
                raise ValueError(
                    "`month` and `day_of_month` are required for YEARLY frequency."
                )
            minute = _format_minute(structured.minute)
            hour = _format_hour(structured.hour)
            return (
                f"{minute} {hour} {structured.day_of_month} "
                f"{structured.month.value} *"
            )

        if freq == ScheduleFrequency.CUSTOM:
            raise ValueError(
                "CUSTOM frequency requires a raw `cron_expression`, not a "
                "structured schedule."
            )

        # Defensive fallback — should be unreachable thanks to enum validation.
        raise ValueError(f"Unsupported schedule frequency: {freq!r}")
    except ValueError:
        raise
    except Exception as exc:
        log.error(f"Unexpected error building cron expression: {exc}", exc_info=True)
        raise ValueError(f"Failed to build cron expression: {exc}") from exc


# ---------------------------------------------------------------------------
# Raw cron expression -> structured (reverse mapping)
# ---------------------------------------------------------------------------


_DOW_NUM_TO_ENUM = {
    0: DayOfWeek.SUNDAY,
    1: DayOfWeek.MONDAY,
    2: DayOfWeek.TUESDAY,
    3: DayOfWeek.WEDNESDAY,
    4: DayOfWeek.THURSDAY,
    5: DayOfWeek.FRIDAY,
    6: DayOfWeek.SATURDAY,
    7: DayOfWeek.SUNDAY,
}

_MONTH_NUM_TO_ENUM = {
    1: Month.JANUARY,
    2: Month.FEBRUARY,
    3: Month.MARCH,
    4: Month.APRIL,
    5: Month.MAY,
    6: Month.JUNE,
    7: Month.JULY,
    8: Month.AUGUST,
    9: Month.SEPTEMBER,
    10: Month.OCTOBER,
    11: Month.NOVEMBER,
    12: Month.DECEMBER,
}

_DOW_DISPLAY_ORDER = {
    DayOfWeek.MONDAY: 1,
    DayOfWeek.TUESDAY: 2,
    DayOfWeek.WEDNESDAY: 3,
    DayOfWeek.THURSDAY: 4,
    DayOfWeek.FRIDAY: 5,
    DayOfWeek.SATURDAY: 6,
    DayOfWeek.SUNDAY: 7,
}

_STEP_RE = re.compile(r"^\*/(\d+)$")


def _parse_int_token(token: str) -> Optional[int]:
    try:
        return int(token)
    except (TypeError, ValueError):
        return None


def _parse_dow_token(token: str) -> Optional[DayOfWeek]:
    t = token.strip().upper()
    if not t:
        return None
    if t.isdigit():
        return _DOW_NUM_TO_ENUM.get(int(t))
    try:
        return DayOfWeek(t)
    except ValueError:
        return None


def _parse_month_token(token: str) -> Optional[Month]:
    t = token.strip().upper()
    if not t:
        return None
    if t.isdigit():
        return _MONTH_NUM_TO_ENUM.get(int(t))
    try:
        return Month(t)
    except ValueError:
        return None


def parse_cron_to_structured(
    cron_expression: Optional[str],
) -> Optional[ScheduleStructured]:
    """Reverse-map a raw cron expression to a `ScheduleStructured`.

    Recognizes only the exact grammars produced by `build_cron_expression`
    (plus numeric DOW/month tokens, which are normalized to enum names).
    Returns ``None`` for any expression outside that grammar — ranges
    (`9-17`), lists in hour/minute slots, non-Unix tokens (`?`, `L`, `#`),
    or 6-field crons with seconds. The UI should then fall back to showing
    only the raw expression and the human-readable text.
    """
    if not cron_expression:
        return None

    parts = cron_expression.strip().split()
    if len(parts) != 5:
        return None
    minute_p, hour_p, dom_p, month_p, dow_p = parts

    try:
        # 1) MINUTELY: */N * * * *
        m_step = _STEP_RE.match(minute_p)
        if (
            m_step
            and hour_p == "*"
            and dom_p == "*"
            and month_p == "*"
            and dow_p == "*"
        ):
            n = int(m_step.group(1))
            if 1 <= n <= 59:
                return ScheduleStructured(
                    frequency=ScheduleFrequency.MINUTELY, interval=n
                )
            return None

        # Minute must be a plain int for all remaining shapes.
        minute = _parse_int_token(minute_p)
        if minute is None or not (0 <= minute <= 59):
            return None

        # 2) HOURLY: M */N * * *
        h_step = _STEP_RE.match(hour_p)
        if h_step and dom_p == "*" and month_p == "*" and dow_p == "*":
            n = int(h_step.group(1))
            if 1 <= n <= 59:
                return ScheduleStructured(
                    frequency=ScheduleFrequency.HOURLY,
                    interval=n,
                    minute=minute,
                )
            return None

        # Hour must be a plain int for daily/weekly/monthly/yearly.
        hour = _parse_int_token(hour_p)
        if hour is None or not (0 <= hour <= 23):
            return None

        # 3) DAILY / MONTHLY (when month=* and dow=*)
        if month_p == "*" and dow_p == "*":
            if dom_p == "*":
                return ScheduleStructured(
                    frequency=ScheduleFrequency.DAILY,
                    interval=1,
                    hour=hour,
                    minute=minute,
                )
            d_step = _STEP_RE.match(dom_p)
            if d_step:
                n = int(d_step.group(1))
                if 1 <= n <= 59:
                    return ScheduleStructured(
                        frequency=ScheduleFrequency.DAILY,
                        interval=n,
                        hour=hour,
                        minute=minute,
                    )
                return None
            # Otherwise: list of integer days-of-month -> MONTHLY
            try:
                days = sorted({int(x) for x in dom_p.split(",") if x})
            except ValueError:
                return None
            if not days or not all(1 <= d <= 31 for d in days):
                return None
            return ScheduleStructured(
                frequency=ScheduleFrequency.MONTHLY,
                hour=hour,
                minute=minute,
                days_of_month=days,
            )

        # 4) WEEKLY: M H * * DOW[,DOW...]
        if dom_p == "*" and month_p == "*" and dow_p != "*":
            tokens = [t for t in dow_p.split(",") if t]
            if not tokens:
                return None
            mapped: List[DayOfWeek] = []
            seen = set()
            for tok in tokens:
                d = _parse_dow_token(tok)
                if d is None:
                    return None
                if d.value not in seen:
                    seen.add(d.value)
                    mapped.append(d)
            mapped.sort(key=lambda d: _DOW_DISPLAY_ORDER[d])
            return ScheduleStructured(
                frequency=ScheduleFrequency.WEEKLY,
                hour=hour,
                minute=minute,
                days_of_week=mapped,
            )

        # 5) YEARLY: M H D MON *  (single dom int, single month token, dow=*)
        if dow_p == "*" and "," not in dom_p and "," not in month_p:
            dom_v = _parse_int_token(dom_p)
            month_v = _parse_month_token(month_p)
            if (
                dom_v is not None
                and 1 <= dom_v <= 31
                and month_v is not None
            ):
                return ScheduleStructured(
                    frequency=ScheduleFrequency.YEARLY,
                    hour=hour,
                    minute=minute,
                    day_of_month=dom_v,
                    month=month_v,
                )
            return None

        return None
    except Exception as exc:
        log.warning(
            f"parse_cron_to_structured failed for '{cron_expression}': {exc}"
        )
        return None


# ---------------------------------------------------------------------------
# Validation + preview
# ---------------------------------------------------------------------------


def validate_cron_expression(cron_expression: str) -> bool:
    """Return True iff `croniter` accepts the expression."""
    if not cron_expression or not cron_expression.strip():
        return False
    try:
        return croniter.is_valid(cron_expression.strip())
    except Exception as exc:  # croniter raises on certain malformed inputs
        log.warning(f"croniter rejected '{cron_expression}': {exc}")
        return False


def get_next_run(
    cron_expression: str,
    timezone_name: Optional[str] = None,
    base: Optional[datetime] = None,
) -> datetime:
    """Compute the next fire time for a cron expression in UTC.

    The `base` time defaults to "now" in the supplied timezone. The returned
    datetime is converted to UTC (timezone-aware) so callers can store it
    consistently in the database.

    Raises:
        ValueError: If the expression or timezone is invalid.
    """
    if not validate_cron_expression(cron_expression):
        raise ValueError(f"Invalid cron expression: {cron_expression!r}")

    tz = resolve_timezone(timezone_name)
    start = base.astimezone(tz) if base else datetime.now(tz)
    try:
        itr = croniter(cron_expression.strip(), start)
        next_local = itr.get_next(datetime)
        return next_local.astimezone(ZoneInfo("UTC"))
    except Exception as exc:
        log.error(
            f"Failed to compute next run for cron='{cron_expression}' "
            f"tz='{timezone_name}': {exc}",
            exc_info=True,
        )
        raise ValueError(f"Could not compute next run: {exc}") from exc


def get_next_n_runs(
    cron_expression: str,
    timezone_name: Optional[str] = None,
    count: int = 5,
    base: Optional[datetime] = None,
) -> List[datetime]:
    """Compute the next `count` fire times in UTC."""
    if not validate_cron_expression(cron_expression):
        raise ValueError(f"Invalid cron expression: {cron_expression!r}")

    tz = resolve_timezone(timezone_name)
    start = base.astimezone(tz) if base else datetime.now(tz)
    utc = ZoneInfo("UTC")

    try:
        itr = croniter(cron_expression.strip(), start)
        return [itr.get_next(datetime).astimezone(utc) for _ in range(count)]
    except Exception as exc:
        log.error(
            f"Failed to compute next {count} runs for '{cron_expression}': {exc}",
            exc_info=True,
        )
        raise ValueError(f"Could not compute next runs: {exc}") from exc


def describe_cron_expression(cron_expression: str) -> Optional[str]:
    """Return a human-readable description of the cron expression.

    Uses `cron-descriptor` when available; falls back to `None` if the
    optional dependency is not installed (the field is documented as
    optional in the response schema).
    """
    try:
        from cron_descriptor import (  # type: ignore[import-not-found]
            ExpressionDescriptor,
            Options,
        )

        options = Options()
        options.use_24hour_time_format = False
        options.verbose = False
        return ExpressionDescriptor(cron_expression.strip(), options).get_description()
    except ImportError:
        # Optional dependency not installed — degrade gracefully.
        return None
    except Exception as exc:
        log.warning(
            f"cron-descriptor failed for '{cron_expression}': {exc}"
        )
        return None


# ---------------------------------------------------------------------------
# Convenience: resolve a request payload to (cron_expression, error)
# ---------------------------------------------------------------------------


def resolve_cron_expression(
    cron_expression: Optional[str],
    structured: Optional[ScheduleStructured],
) -> Tuple[Optional[str], Optional[str]]:
    """Return `(cron_expression, error_message)` for a create/update payload.

    The caller is expected to have already enforced exactly-one-of via
    Pydantic validation. This helper builds the structured form into a raw
    expression and then validates whichever expression is in play.
    """
    try:
        if cron_expression:
            expr = cron_expression.strip()
        elif structured is not None:
            expr = build_cron_expression(structured)
        else:
            return None, "Either `cron_expression` or `schedule` must be provided."
    except ValueError as exc:
        return None, str(exc)

    if not validate_cron_expression(expr):
        return None, f"Invalid cron expression: '{expr}'."
    return expr, None
