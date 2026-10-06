# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""Pydantic schemas and enums for the cron scheduler subsystem.

All enums in this module are intentionally exposed in the public OpenAPI
schema so the UI team can render dropdowns directly from `/openapi.json`
or via the dedicated `/chat/schedules/enums` bootstrap endpoint.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.config.constants import FrameworkType


# ---------------------------------------------------------------------------
# Enums (rendered as Swagger dropdowns)
# ---------------------------------------------------------------------------


class ScheduleFrequency(str, Enum):
    """High-level schedule cadence chosen by the UI form.

    `CUSTOM` indicates the caller will supply a raw `cron_expression`
    instead of a structured `schedule` object.
    """

    MINUTELY = "minutely"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    CUSTOM = "custom"


class DayOfWeek(str, Enum):
    """Cron day-of-week tokens (matches Unix cron syntax)."""

    MONDAY = "MON"
    TUESDAY = "TUE"
    WEDNESDAY = "WED"
    THURSDAY = "THU"
    FRIDAY = "FRI"
    SATURDAY = "SAT"
    SUNDAY = "SUN"


class Month(str, Enum):
    """Cron month tokens (matches Unix cron syntax)."""

    JANUARY = "JAN"
    FEBRUARY = "FEB"
    MARCH = "MAR"
    APRIL = "APR"
    MAY = "MAY"
    JUNE = "JUN"
    JULY = "JUL"
    AUGUST = "AUG"
    SEPTEMBER = "SEP"
    OCTOBER = "OCT"
    NOVEMBER = "NOV"
    DECEMBER = "DEC"


class CommonTimezone(str, Enum):
    """Curated list of widely-used IANA timezones for UI dropdowns.

    Free-form IANA timezone strings are also accepted at the API boundary
    (validated server-side), so power users are not constrained to this list.
    """

    UTC = "UTC"
    ASIA_KOLKATA = "Asia/Kolkata"
    ASIA_DUBAI = "Asia/Dubai"
    ASIA_SINGAPORE = "Asia/Singapore"
    ASIA_TOKYO = "Asia/Tokyo"
    ASIA_SHANGHAI = "Asia/Shanghai"
    EUROPE_LONDON = "Europe/London"
    EUROPE_PARIS = "Europe/Paris"
    EUROPE_BERLIN = "Europe/Berlin"
    AMERICA_NEW_YORK = "America/New_York"
    AMERICA_CHICAGO = "America/Chicago"
    AMERICA_LOS_ANGELES = "America/Los_Angeles"
    AMERICA_SAO_PAULO = "America/Sao_Paulo"
    AUSTRALIA_SYDNEY = "Australia/Sydney"


class ScheduleExecutionStatus(str, Enum):
    """Per-execution outcome stored in the history table."""

    QUEUED = "queued"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------


class ScheduleStructured(BaseModel):
    """Friendly structured representation of a schedule.

    The backend converts this to a raw cron expression. Which fields are
    required depends on `frequency`:

    - MINUTELY: `interval`
    - HOURLY:   `interval`, optional `minute`
    - DAILY:    `interval`, `hour`, `minute`
    - WEEKLY:   `days_of_week`, `hour`, `minute`
    - MONTHLY:  `days_of_month`, `hour`, `minute`
    - YEARLY:   `month`, `day_of_month`, `hour`, `minute`
    """

    frequency: ScheduleFrequency = Field(
        ..., description="High-level cadence for the schedule."
    )
    interval: int = Field(
        default=1,
        ge=1,
        le=59,
        description="Repetition gap (used for minutely / hourly / daily).",
    )
    hour: Optional[int] = Field(
        default=None, ge=0, le=23, description="Hour-of-day anchor (0-23)."
    )
    minute: Optional[int] = Field(
        default=None, ge=0, le=59, description="Minute-of-hour anchor (0-59)."
    )
    days_of_week: Optional[List[DayOfWeek]] = Field(
        default=None, description="Required for WEEKLY frequency."
    )
    days_of_month: Optional[List[int]] = Field(
        default=None, description="Required for MONTHLY frequency. Each value 1-31."
    )
    month: Optional[Month] = Field(
        default=None, description="Required for YEARLY frequency."
    )
    day_of_month: Optional[int] = Field(
        default=None, ge=1, le=31, description="Required for YEARLY frequency."
    )

    @field_validator("days_of_month")
    @classmethod
    def _validate_days_of_month(cls, value):
        if value is None:
            return value
        for day in value:
            if not 1 <= day <= 31:
                raise ValueError(f"days_of_month value {day} must be between 1 and 31")
        return value


class InferenceFlags(BaseModel):
    """Inference behaviour flags persisted with the schedule.

    Mirrors the relevant subset of `AgentInferenceRequest` so scheduled
    runs can use the same feature toggles available in interactive runs.
    """

    evaluation_flag: bool = False
    validator_flag: bool = False
    context_flag: bool = True
    file_context_management_flag: bool = False
    response_formatting_flag: bool = False
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ScheduledJobCreateRequest(BaseModel):
    """Request payload for `POST /chat/schedules`.

    Provide EITHER `cron_expression` (advanced mode) OR `schedule`
    (structured mode), never both.
    """

    schedule_name: str = Field(
        ..., min_length=1, max_length=200, description="User-friendly label."
    )
    description: Optional[str] = Field(
        default=None, max_length=2000, description="Optional notes."
    )

    agentic_application_id: str = Field(
        ..., description="The agent or workflow to invoke on each fire."
    )
    query: str = Field(..., min_length=1, description="The query passed to the agent.")
    model_name: str = Field(..., description="The LLM model to use.")
    framework_type: FrameworkType = Field(
        default=FrameworkType.LANGGRAPH, description="Framework type of the target agent."
    )

    cron_expression: Optional[str] = Field(
        default=None,
        description="Raw 5-field Unix cron expression. Mutually exclusive with `schedule`.",
    )
    schedule: Optional[ScheduleStructured] = Field(
        default=None,
        description="Structured schedule definition. Mutually exclusive with `cron_expression`.",
    )

    timezone: str = Field(
        default="Asia/Kolkata",
        description="IANA timezone in which the cron expression is interpreted.",
    )
    is_active: bool = Field(default=True, description="Whether the schedule fires.")

    max_runs: Optional[int] = Field(
        default=None,
        ge=1,
        description="Auto-disable after this many successful runs. Null = unlimited.",
    )
    end_date: Optional[datetime] = Field(
        default=None, description="Auto-disable after this UTC datetime."
    )
    max_consecutive_failures: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Auto-pause the schedule after N consecutive failures.",
    )

    inference_flags: InferenceFlags = Field(
        default_factory=InferenceFlags,
        description="Inference behaviour flags applied to every scheduled run.",
    )

    @model_validator(mode="after")
    def _exactly_one_schedule_form(self):
        has_raw = bool(self.cron_expression and self.cron_expression.strip())
        has_structured = self.schedule is not None
        if has_raw and has_structured:
            raise ValueError(
                "Provide EITHER `cron_expression` OR `schedule`, not both."
            )
        if not has_raw and not has_structured:
            raise ValueError(
                "Either `cron_expression` or `schedule` must be provided."
            )
        return self


class ScheduledJobUpdateRequest(BaseModel):
    """Request payload for `PATCH /chat/schedules/{job_id}`.

    All fields are optional. Provide only what you want to change.
    Cron expression updates follow the same either/or rule as create.
    """

    schedule_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    query: Optional[str] = Field(default=None, min_length=1)
    model_name: Optional[str] = None
    framework_type: Optional[FrameworkType] = None
    cron_expression: Optional[str] = None
    schedule: Optional[ScheduleStructured] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None
    max_runs: Optional[int] = Field(default=None, ge=1)
    end_date: Optional[datetime] = None
    max_consecutive_failures: Optional[int] = Field(default=None, ge=1, le=100)
    inference_flags: Optional[InferenceFlags] = None

    @model_validator(mode="after")
    def _no_double_schedule(self):
        if self.cron_expression and self.schedule is not None:
            raise ValueError(
                "Provide EITHER `cron_expression` OR `schedule`, not both."
            )
        return self


class ValidateCronRequest(BaseModel):
    """Request payload for `POST /chat/schedules/validate-cron`.

    Accepts either a raw cron expression or a structured schedule, and
    returns the canonical cron string plus a preview of the next runs.
    """

    cron_expression: Optional[str] = Field(default=None)
    schedule: Optional[ScheduleStructured] = Field(default=None)
    timezone: str = Field(default="Asia/Kolkata")

    @model_validator(mode="after")
    def _exactly_one_form(self):
        if self.cron_expression and self.schedule is not None:
            raise ValueError(
                "Provide EITHER `cron_expression` OR `schedule`, not both."
            )
        if not self.cron_expression and self.schedule is None:
            raise ValueError(
                "Either `cron_expression` or `schedule` must be provided."
            )
        return self


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ScheduledJobResponse(BaseModel):
    """Single schedule projection returned by GET / list endpoints."""

    job_id: str
    schedule_name: str
    description: Optional[str] = None

    agentic_application_id: str
    query: str
    model_name: str
    framework_type: FrameworkType

    cron_expression: str
    timezone: str
    human_readable: Optional[str] = None
    schedule: Optional[ScheduleStructured] = Field(
        default=None,
        description=(
            "Reverse-mapped structured form of `cron_expression`. Populated "
            "only when the cron expression matches one of the grammars the "
            "structured builder can produce; otherwise null (UI should fall "
            "back to the raw `cron_expression`)."
        ),
    )

    is_active: bool
    is_deleted: bool = False

    max_runs: Optional[int] = None
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    consecutive_failure_count: int = 0
    max_consecutive_failures: int = 5
    end_date: Optional[datetime] = None

    inference_flags: InferenceFlags = Field(default_factory=InferenceFlags)

    created_by: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None


class ScheduledJobListResponse(BaseModel):
    """Wrapper response for list endpoints."""

    total: int
    schedules: List[ScheduledJobResponse]


class ScheduleExecutionRecord(BaseModel):
    """Single past execution as listed by the history endpoint."""

    execution_id: str
    job_id: str
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    status: ScheduleExecutionStatus
    scheduled_at: datetime
    dispatched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class ScheduleExecutionDetailResponse(ScheduleExecutionRecord):
    """
    Detailed execution record. Chat history is fetched live from the
    short-term memory store keyed by `(agentic_application_id, session_id)`.

    If the underlying chat session has been deleted, `chat_history` will be
    `null` and `chat_history_error` will explain why.
    """

    chat_history: Optional[Dict[str, Any]] = None
    chat_history_error: Optional[str] = None


class ScheduleHistoryListResponse(BaseModel):
    """Wrapper response for history endpoint."""

    total: int
    job_id: str
    executions: List[ScheduleExecutionRecord]


class ValidateCronResponse(BaseModel):
    """Response payload for `POST /chat/schedules/validate-cron`."""

    valid: bool
    cron_expression: str
    timezone: str
    human_readable: Optional[str] = None
    schedule: Optional[ScheduleStructured] = Field(
        default=None,
        description=(
            "Reverse-mapped structured form of `cron_expression`. Populated "
            "only when the expression matches one of the recognized "
            "grammars; otherwise null."
        ),
    )
    next_runs: List[datetime] = Field(default_factory=list)
    error: Optional[str] = None


class UpcomingRunEntry(BaseModel):
    """Entry returned by the `/chat/schedules/upcoming` dashboard endpoint."""

    job_id: str
    schedule_name: str
    cron_expression: str
    timezone: str
    next_run_at: datetime


class UpcomingRunsResponse(BaseModel):
    total: int
    upcoming: List[UpcomingRunEntry]


class RunNowResponse(BaseModel):
    """Response payload for `POST /chat/schedules/{job_id}/run-now`."""

    job_id: str
    task_id: str
    session_id: str
    execution_id: Optional[str] = None
    success: bool
    error: Optional[str] = None


class SchedulerEnumsResponse(BaseModel):
    """Bootstrap response for the UI dropdowns."""

    frequencies: List[str]
    days_of_week: List[str]
    months: List[str]
    timezones: List[str]
    framework_types: List[str]
    execution_statuses: List[str]
