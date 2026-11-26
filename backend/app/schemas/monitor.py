from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.schemas.common import utc_iso

Method = Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]
# Headers the client controls; letting a monitor set them breaks the request.
FORBIDDEN_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}


def _check_headers(value: dict[str, str]) -> dict[str, str]:
    if len(value) > 10:
        raise ValueError("at most 10 custom headers")
    for name, header in value.items():
        if name.lower() in FORBIDDEN_HEADERS:
            raise ValueError(f"{name} header cannot be set by a monitor")
        if len(name) > 64 or len(str(header)) > 1024:
            raise ValueError(f"{name} header is too long")
    return {str(k): str(v) for k, v in value.items()}


class MonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    url: str = Field(max_length=2048)
    method: Method = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    interval_seconds: int = Field(default=60, ge=10, le=86_400)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    expected_status: int = Field(default=200, ge=100, le=599)
    failure_threshold: int | None = Field(default=None, ge=1, le=10)
    degraded_ms: int | None = Field(default=None, ge=50, le=60_000)
    enabled: bool = True

    @field_validator("headers")
    @classmethod
    def _headers(cls, value: dict[str, str]) -> dict[str, str]:
        return _check_headers(value)


class MonitorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    url: str | None = Field(default=None, max_length=2048)
    method: Method | None = None
    headers: dict[str, str] | None = None
    interval_seconds: int | None = Field(default=None, ge=10, le=86_400)
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    expected_status: int | None = Field(default=None, ge=100, le=599)
    failure_threshold: int | None = Field(default=None, ge=1, le=10)
    degraded_ms: int | None = Field(default=None, ge=50, le=60_000)
    enabled: bool | None = None

    @field_validator("headers")
    @classmethod
    def _headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _check_headers(value) if value is not None else None


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    method: str
    headers: dict[str, Any]
    interval_seconds: int
    timeout_seconds: int
    expected_status: int
    failure_threshold: int
    degraded_ms: int
    enabled: bool
    status: str
    consecutive_failures: int
    last_checked_at: datetime | None
    next_check_at: datetime | None
    last_response_ms: int | None
    last_error: str | None
    created_at: datetime

    # Filled in by the route from the checks table.
    uptime_24h: float | None = None
    sparkline: list[int | None] = []
    open_incident_id: int | None = None

    @field_serializer("last_checked_at", "next_check_at", "created_at")
    def _as_utc(self, value: datetime | None) -> str | None:
        return utc_iso(value)


class MonitorDetail(MonitorOut):
    uptime: dict[str, Any] = {}
    response_series: list[dict[str, Any]] = []
    avg_response_ms: int | None = None
