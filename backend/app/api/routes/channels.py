"""Notification channels. Credentials are encrypted in, masked out."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import APIError
from app.core.net import UnsafeTargetError, validate_target
from app.core.security import encrypt_secret, mask
from app.db.session import get_db
from app.models import ChannelType, Incident, IncidentStatus, Monitor, NotificationChannel, User
from app.schemas.monitoring import ChannelCreate, ChannelOut, ChannelUpdate
from app.services import notifications

router = APIRouter(prefix="/api/channels", tags=["notification channels"])

# Which config field holds the credential for each channel type.
SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    "discord": ("webhook_url",),
    "telegram": ("bot_token",),
    "webhook": ("url",),
}
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "discord": ("webhook_url",),
    "telegram": ("bot_token", "chat_id"),
    "webhook": ("url",),
}


def _prepare_config(channel_type: str, config: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS[channel_type] if not config.get(field)]
    if missing:
        raise APIError("invalid_channel", f"Missing: {', '.join(missing)}", 422)

    prepared: dict[str, Any] = {}
    for key, value in config.items():
        if key in SECRET_FIELDS[channel_type] and isinstance(value, str):
            if key in ("webhook_url", "url"):
                try:
                    validate_target(value, require_https=channel_type == "discord")
                except UnsafeTargetError as exc:
                    raise APIError("unsafe_target", str(exc), 422) from exc
            # Encrypted at rest; the plain value never leaves this function.
            prepared[key] = {"__enc__": encrypt_secret(value), "hint": mask(value)}
        else:
            prepared[key] = value
    return prepared


def _redact(config: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (config or {}).items():
        out[key] = value.get("hint", "••••••") if isinstance(value, dict) and "__enc__" in value else value
    return out


def _out(channel: NotificationChannel) -> ChannelOut:
    return ChannelOut(
        **ChannelOut.model_validate(channel).model_dump(exclude={"config"}),
        config=_redact(channel.config),
    )


def _owned(db: Session, user: User, channel_id: int) -> NotificationChannel:
    channel = db.get(NotificationChannel, channel_id)
    if channel is None or channel.user_id != user.id:
        raise APIError("not_found", "Channel not found.", 404)
    return channel


@router.get("", response_model=list[ChannelOut], summary="List channels")
def list_channels(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ChannelOut]:
    channels = db.execute(
        select(NotificationChannel)
        .where(NotificationChannel.user_id == user.id)
        .order_by(NotificationChannel.created_at)
    ).scalars().all()
    return [_out(channel) for channel in channels]


@router.post("", response_model=ChannelOut, status_code=201, summary="Add a channel")
def create_channel(
    payload: ChannelCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChannelOut:
    channel = NotificationChannel(
        user_id=user.id,
        name=payload.name,
        type=payload.type,
        config=_prepare_config(payload.type, payload.config),
        enabled=payload.enabled,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return _out(channel)


@router.patch("/{channel_id}", response_model=ChannelOut, summary="Update a channel")
def update_channel(
    payload: ChannelUpdate,
    channel_id: int = Path(ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChannelOut:
    channel = _owned(db, user, channel_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise APIError("nothing_to_update", "No fields to update.", 400)

    if "config" in changes and changes["config"] is not None:
        channel.config = _prepare_config(channel.type, changes.pop("config"))
    for field, value in changes.items():
        if value is not None:
            setattr(channel, field, value)

    db.commit()
    db.refresh(channel)
    return _out(channel)


@router.delete("/{channel_id}", status_code=204, summary="Delete a channel")
def delete_channel(
    channel_id: int = Path(ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    db.delete(_owned(db, user, channel_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{channel_id}/test", summary="Send a test alert")
async def test_channel(
    channel_id: int = Path(ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delivers a real alert built from a sample incident, so the channel is
    proven end to end rather than 'saved successfully'."""
    channel = _owned(db, user, channel_id)

    sample_monitor = Monitor(
        id=0, user_id=user.id, name="PulseWatch test", url="https://example.com/health"
    )
    sample_incident = Incident(
        id=0,
        monitor_id=0,
        user_id=user.id,
        status=IncidentStatus.OPEN,
        reason="This is a test alert from PulseWatch",
        failure_count=1,
    )
    alert = notifications.build_alert(sample_monitor, sample_incident, recovered=False)

    ok, detail = await notifications._send(channel, alert)  # noqa: SLF001 - same module's API
    channel.last_error = None if ok else detail[:255]
    db.commit()
    return {"delivered": ok, "detail": detail, "channel": channel.name}


@router.get("/types", summary="Channel types and the fields they need")
def channel_types() -> list[dict[str, Any]]:
    return [
        {
            "type": ChannelType.DISCORD,
            "label": "Discord",
            "fields": [{"name": "webhook_url", "secret": True, "label": "Webhook URL"}],
        },
        {
            "type": ChannelType.TELEGRAM,
            "label": "Telegram",
            "fields": [
                {"name": "bot_token", "secret": True, "label": "Bot token"},
                {"name": "chat_id", "secret": False, "label": "Chat ID"},
            ],
        },
        {
            "type": ChannelType.WEBHOOK,
            "label": "Webhook",
            "fields": [{"name": "url", "secret": True, "label": "Endpoint URL"}],
        },
    ]
