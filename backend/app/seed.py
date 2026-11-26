"""Demo data: ``python -m app.seed``.

Creates one clearly marked demo account with four monitors pointed at this
project's own ``/demo`` endpoints, then **runs real checks** against them —
including one service that is always down, so the dashboard shows an open
incident with a timeline rather than an empty state.

No check rows or incidents are fabricated: the engine produces them. The
requests are routed straight into the ASGI app with httpx's ASGI transport, so
seeding works without a server running.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx

from app.core.config import settings
from app.core.security import encrypt_secret, hash_password, mask
from app.db.base import utcnow
from app.db.session import SessionLocal, init_db
from app.models import ChannelType, Monitor, MonitorStatus, NotificationChannel, StatusPage, User
from app.services import incidents as incident_engine
from app.services.checker import CheckTarget, run_check
from app.services.http_client import set_transport

DEMO_EMAIL = "demo@pulsewatch.dev"
DEMO_PASSWORD = "pulsewatch-demo-1234"
ROUNDS = 12

MONITORS = [
    {
        "name": "Production API",
        "path": "/demo/healthy",
        "interval_seconds": 60,
        "degraded_ms": 1500,
    },
    {
        "name": "Marketing site",
        "path": "/demo/slow?seconds=0.4",
        "interval_seconds": 120,
        # Deliberately strict, so this one reports as degraded rather than down.
        "degraded_ms": 200,
    },
    {
        "name": "Checkout service",
        "path": "/demo/error",
        "interval_seconds": 60,
        "degraded_ms": 1500,
    },
    {
        "name": "Auth service",
        "path": "/demo/flaky",
        "interval_seconds": 60,
        "degraded_ms": 1500,
    },
]


async def seed(reset: bool) -> int:
    init_db()

    with SessionLocal() as db:
        existing = db.query(User).filter(User.email == DEMO_EMAIL).one_or_none()
        if existing and not reset:
            print(f"Demo account already exists: {DEMO_EMAIL}")
            print("Re-run with --reset to rebuild it.")
            return 0
        if existing:
            db.delete(existing)
            db.commit()

        user = User(
            email=DEMO_EMAIL,
            name="Demo Account",
            password_hash=hash_password(DEMO_PASSWORD),
            is_demo=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        created: list[Monitor] = []
        for spec in MONITORS:
            monitor = Monitor(
                user_id=user.id,
                name=spec["name"],
                url=f"{settings.public_api_url}{spec['path']}",
                method="GET",
                interval_seconds=spec["interval_seconds"],
                timeout_seconds=10,
                expected_status=200,
                failure_threshold=settings.default_failure_threshold,
                degraded_ms=spec["degraded_ms"],
                status=MonitorStatus.PENDING,
                next_check_at=utcnow(),
            )
            db.add(monitor)
            created.append(monitor)
        db.commit()
        for monitor in created:
            db.refresh(monitor)

        # A notification channel, so the alert UI has something to show. The
        # credential is encrypted exactly as a real one would be.
        webhook_url = "https://example.com/pulsewatch-demo-hook"
        db.add(
            NotificationChannel(
                user_id=user.id,
                name="Ops webhook (demo)",
                type=ChannelType.WEBHOOK,
                config={"url": {"__enc__": encrypt_secret(webhook_url), "hint": mask(webhook_url)}},
            )
        )

        db.add(
            StatusPage(
                user_id=user.id,
                slug="acme",
                title="Acme Platform",
                description="Live availability of the Acme platform services.",
                monitor_ids=[monitor.id for monitor in created],
            )
        )
        db.commit()

        # Route checks into this very app: real engine, real endpoints, no
        # server process required.
        from app.main import app

        set_transport(httpx.ASGITransport(app=app))
        try:
            for _ in range(ROUNDS):
                for monitor in created:
                    fresh = db.get(Monitor, monitor.id)
                    if fresh is None:
                        continue
                    result = await run_check(
                        CheckTarget(
                            url=fresh.url,
                            method=fresh.method,
                            timeout_seconds=float(fresh.timeout_seconds),
                            expected_status=fresh.expected_status,
                            degraded_ms=fresh.degraded_ms,
                        )
                    )
                    incident_engine.record_check(db, fresh, result)
        finally:
            set_transport(None)

        summary = [
            (monitor.name, db.get(Monitor, monitor.id).status) for monitor in created
        ]

    print("Demo data ready.")
    print(f"  email:    {DEMO_EMAIL}")
    print(f"  password: {DEMO_PASSWORD}")
    print(f"  checks:   {ROUNDS} rounds per monitor, run by the real engine")
    for name, status in summary:
        print(f"    {name:20} {status}")
    print("\nPublic status page: /status/acme")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Rebuild the demo account.")
    args = parser.parse_args()
    return asyncio.run(seed(args.reset))


if __name__ == "__main__":
    sys.exit(main())
