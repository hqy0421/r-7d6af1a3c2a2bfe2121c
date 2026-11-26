"""Maintenance commands: ``python -m app.cli <command>``."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.config import settings
from app.db.session import SessionLocal, init_db
from app.models import MonitorCheck

COMMANDS = ("init-db", "prune-checks")


def prune_checks(days: int | None = None) -> int:
    """Delete checks older than the retention window.

    A command rather than a background job: on this scale a cron entry is
    honest, and a scheduler would be one more moving part to get wrong.
    """
    retention = settings.check_retention_days if days is None else days
    if retention <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
    with SessionLocal() as db:
        result = db.execute(delete(MonitorCheck).where(MonitorCheck.checked_at < cutoff))
        db.commit()
        return result.rowcount or 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in COMMANDS:
        print(f"usage: python -m app.cli [{' | '.join(COMMANDS)}]")
        return 1

    if args[0] == "init-db":
        init_db()
        print(f"Schema created in {settings.database_url}")
        return 0

    deleted = prune_checks()
    print(f"Deleted {deleted} checks older than {settings.check_retention_days} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
