"""Outbound target validation — the SSRF guard.

A monitoring product exists to make HTTP requests on a user's behalf, which is
exactly the shape of an SSRF primitive: without this, "monitor
http://169.254.169.254/latest/meta-data/" would happily print cloud
credentials into a check result.

Every monitor URL and every notification destination passes through
:func:`validate_target` before a request is made.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.config import settings

ALLOWED_SCHEMES = {"http", "https"}
# The bundled /demo endpoints are served by this process, so they are allowed
# even with the guard on: a demo must not require disabling a security control.
DEMO_PATH_PREFIX = "/demo/"


class UnsafeTargetError(ValueError):
    """The URL may not be requested."""


def is_demo_target(url: str) -> bool:
    parsed = urlparse(url.strip())
    base = urlparse(settings.public_api_url)
    return (
        parsed.path.startswith(DEMO_PATH_PREFIX)
        and parsed.hostname == base.hostname
        and (parsed.port or _default_port(parsed.scheme)) == (base.port or _default_port(base.scheme))
    )


def validate_target(url: str, *, require_https: bool = False) -> str:
    parsed = urlparse(url.strip())

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeTargetError("URL must start with http:// or https://")
    if require_https and parsed.scheme != "https":
        raise UnsafeTargetError("URL must use https://")
    if not parsed.hostname:
        raise UnsafeTargetError("URL has no host")
    if parsed.username or parsed.password:
        raise UnsafeTargetError("Credentials in the URL are not allowed")
    if len(url) > 2048:
        raise UnsafeTargetError("URL is too long")

    if settings.allow_private_network_targets or is_demo_target(url):
        return url

    for address in _resolve(parsed.hostname):
        if (
            address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_multicast or address.is_unspecified
        ):
            raise UnsafeTargetError(
                f"{parsed.hostname} resolves to a private address ({address}); "
                "monitors may only target public hosts"
            )
    return url


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _resolve(hostname: str):
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeTargetError(f"{hostname} could not be resolved") from exc
    return [ipaddress.ip_address(info[4][0]) for info in infos]
