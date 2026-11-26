"""Alert delivery.

Three channel types behind one function: the incident engine hands over a
transition, and this module renders it and posts it. Credentials are decrypted
here and nowhere else, and never appear in a log line or an error message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.net import UnsafeTargetError, validate_target
from app.core.security import decrypt_secret
from app.db.base import utcnow
from app.models import ChannelType, Incident, Monitor, NotificationChannel
from app.services.http_client import get_client
from app.services.incidents import format_duration

logger = logging.getLogger("pulsewatch.notifications")

TELEGRAM_API = "https://api.telegram.org"


@dataclass(slots=True)
class Alert:
    kind: str  # "down" | "recovered"
    title: str
    body: str
    payload: dict[str, Any]


def build_alert(monitor: Monitor, incident: Incident, *, recovered: bool) -> Alert:
    """Render an alert.

    Timestamps fall back to "now" because this is also called with an
    in-memory incident — the channel test endpoint builds one that is never
    written, and a None here would crash the very button meant to prove a
    channel works.
    """
    started_at = incident.started_at or utcnow()
    resolved_at = incident.resolved_at or utcnow()
    if recovered:
        downtime = format_duration(incident.duration_seconds)
        return Alert(
            kind="recovered",
            title=f"🟢 {monitor.name} recovered",
            body=(
                f"**Monitor:** {monitor.name}\n"
                f"**URL:** {monitor.url}\n"
                f"**Downtime:** {downtime}\n"
                f"**Recovered:** {resolved_at.isoformat()}"
            ),
            payload={
                "event": "monitor.recovered",
                "monitor": {"id": monitor.id, "name": monitor.name, "url": monitor.url},
                "incident_id": incident.id,
                "downtime_seconds": incident.duration_seconds,
            },
        )
    return Alert(
        kind="down",
        title=f"🔴 {monitor.name} is DOWN",
        body=(
            f"**Monitor:** {monitor.name}\n"
            f"**URL:** {monitor.url}\n"
            f"**Reason:** {incident.reason}\n"
            f"**Failed checks:** {incident.failure_count}\n"
            f"**Detected:** {started_at.isoformat()}"
        ),
        payload={
            "event": "monitor.down",
            "monitor": {"id": monitor.id, "name": monitor.name, "url": monitor.url},
            "incident_id": incident.id,
            "reason": incident.reason,
            "failure_count": incident.failure_count,
        },
    )


async def dispatch(db: Session, user_id: int, alert: Alert) -> list[str]:
    """Send the alert to every enabled channel. Returns human-readable results."""
    channels = db.execute(
        select(NotificationChannel).where(
            NotificationChannel.user_id == user_id, NotificationChannel.enabled.is_(True)
        )
    ).scalars().all()

    results: list[str] = []
    for channel in channels:
        ok, detail = await _send(channel, alert)
        channel.last_used_at = utcnow()
        if ok:
            channel.delivered_count += 1
            channel.last_error = None
        else:
            channel.failed_count += 1
            channel.last_error = detail[:255]
        results.append(f"{channel.name}: {detail}")
    db.commit()
    return results


async def _send(channel: NotificationChannel, alert: Alert) -> tuple[bool, str]:
    if settings.notifications_dry_run:
        # Rendered and recorded, never sent: used by demos and the test suite.
        logger.info("[dry-run] %s → %s: %s", channel.type, channel.name, alert.title)
        return True, "dry-run (not sent)"

    try:
        return await _deliver(channel, alert)
    except UnsafeTargetError as exc:
        return False, str(exc)
    except httpx.HTTPError as exc:
        # The URL may embed a token, so the type is reported, never the URL.
        return False, f"Network error: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001 - a broken channel must not stop the engine
        logger.exception("Notification failed for channel %s", channel.id)
        return False, f"Delivery error: {type(exc).__name__}"


async def _deliver(channel: NotificationChannel, alert: Alert) -> tuple[bool, str]:
    client = get_client()
    config = channel.config or {}

    if channel.type == ChannelType.DISCORD:
        url = _secret(config, "webhook_url")
        if not url:
            return False, "No webhook URL configured"
        validate_target(url, require_https=True)
        response = await client.post(
            url,
            json={"content": f"{alert.title}\n\n{alert.body}"},
            timeout=10.0,
        )
        return _http_result(response, (200, 204))

    if channel.type == ChannelType.TELEGRAM:
        token = _secret(config, "bot_token")
        chat_id = config.get("chat_id")
        if not token or not chat_id:
            return False, "Bot token or chat ID missing"
        # The token is part of the URL, so the URL itself is a credential and
        # is never logged or returned.
        response = await client.post(
            f"{TELEGRAM_API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"{alert.title}\n\n{_plain(alert.body)}"},
            timeout=10.0,
        )
        return _http_result(response, (200,))

    if channel.type == ChannelType.WEBHOOK:
        url = _secret(config, "url")
        if not url:
            return False, "No URL configured"
        validate_target(url)
        headers = {
            key: str(value) for key, value in (config.get("headers") or {}).items()
        }
        response = await client.post(url, json=alert.payload, headers=headers, timeout=10.0)
        return _http_result(response, tuple(range(200, 300)))

    return False, f"Unknown channel type '{channel.type}'"


def _secret(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    if isinstance(value, dict) and "__enc__" in value:
        return decrypt_secret(value["__enc__"])
    return value if isinstance(value, str) else None


def _http_result(response: httpx.Response, accepted: tuple[int, ...]) -> tuple[bool, str]:
    if response.status_code in accepted:
        return True, f"delivered ({response.status_code})"
    return False, f"rejected with {response.status_code}"


def _plain(markdown: str) -> str:
    return markdown.replace("**", "")
