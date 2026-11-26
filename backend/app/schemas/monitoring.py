from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas.common import utc_iso


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    outcome: str
    status_code: int | None
    response_ms: int | None
    error: str | None
    manual: bool
    checked_at: datetime

    @field_serializer("checked_at")
    def _as_utc(self, value: datetime) -> str | None:
        return utc_iso(value)


class CheckPage(BaseModel):
    items: list[CheckOut]
    total: int
    limit: int
    offset: int


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    status: str
    reason: str
    failure_count: int
    started_at: datetime
    resolved_at: datetime | None
    duration_seconds: int | None
    timeline: list[dict[str, Any]]
    notes: str | None

    # Filled in by the route.
    monitor_name: str | None = None
    monitor_url: str | None = None

    @field_serializer("started_at", "resolved_at")
    def _as_utc(self, value: datetime | None) -> str | None:
        return utc_iso(value)


class IncidentPage(BaseModel):
    items: list[IncidentOut]
    total: int
    limit: int
    offset: int


class ManualCheckResult(BaseModel):
    """What the "Run check now" button gets back."""

    outcome: str
    status_code: int | None
    response_ms: int | None
    error: str | None
    monitor_status: str
    checked_at: datetime

    @field_serializer("checked_at")
    def _as_utc(self, value: datetime) -> str | None:
        return utc_iso(value)


class ChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    type: Literal["discord", "telegram", "webhook"]
    config: dict[str, Any]
    enabled: bool = True


class ChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    enabled: bool
    config: dict[str, Any]      # credentials masked by the route
    last_used_at: datetime | None
    last_error: str | None
    delivered_count: int
    failed_count: int
    created_at: datetime

    @field_serializer("last_used_at", "created_at")
    def _as_utc(self, value: datetime | None) -> str | None:
        return utc_iso(value)


class StatusPageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=2, max_length=48, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    title: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    monitor_ids: list[int] = Field(default_factory=list)
    published: bool = True


class StatusPageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    monitor_ids: list[int] | None = None
    published: bool | None = None


class StatusPageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    description: str | None
    monitor_ids: list[int]
    published: bool
    created_at: datetime

    @field_serializer("created_at")
    def _as_utc(self, value: datetime) -> str | None:
        return utc_iso(value)


class PublicService(BaseModel):
    name: str
    status: str
    uptime_24h: float | None
    uptime_30d: float | None
    last_checked_at: datetime | None

    @field_serializer("last_checked_at")
    def _as_utc(self, value: datetime | None) -> str | None:
        return utc_iso(value)


class PublicIncident(BaseModel):
    id: int
    service: str
    status: str
    reason: str
    started_at: datetime
    resolved_at: datetime | None
    duration_seconds: int | None
    timeline: list[dict[str, Any]]

    @field_serializer("started_at", "resolved_at")
    def _as_utc(self, value: datetime | None) -> str | None:
        return utc_iso(value)


class PublicStatusPage(BaseModel):
    """Everything the public page needs — and nothing else.

    No URLs, no configuration, no owner: a status page is public, so it says
    what is up and what happened, not how it is monitored.
    """

    slug: str
    title: str
    description: str | None
    overall: str
    services: list[PublicService]
    incidents: list[PublicIncident]
    updated_at: datetime

    @field_serializer("updated_at")
    def _as_utc(self, value: datetime) -> str | None:
        return utc_iso(value)


class DashboardOut(BaseModel):
    monitors: int
    operational: int
    degraded: int
    down: int
    paused: int
    pending: int
    open_incidents: int
    checks_24h: int
    uptime_24h: float | None
    avg_response_ms: int | None
