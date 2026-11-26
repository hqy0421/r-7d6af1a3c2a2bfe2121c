"""Maintenance commands: ``python -m app.cli <command>``."""

from __future__ import annotations

import sys
from app.core.config import settings
from app.db.session import init_db
from app.services.error_budget import prune_checks

COMMANDS = ("init-db", "prune-checks")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in COMMANDS:
        print(f"usage: python -m app.cli [{' | '.join(COMMANDS)}]")
        return 1

    if args[0] == "init-db":
        init_db()
        print(f"Schema created in {settings.database_url}")
        return 0

    days: int | None = None
    positional: list[str] = []
    index = 1
    while index < len(args):
        option = args[index]
        if option in {"--days", "-d", "--retention-days", "--older-than-days"}:
            if index + 1 >= len(args):
                print("usage: python -m app.cli prune-checks [--days N]")
                return 1
            days = int(args[index + 1])
            index += 2
            continue
        if "=" in option and option.split("=", 1)[0] in {
            "--days",
            "--retention-days",
            "--older-than-days",
        }:
            days = int(option.split("=", 1)[1])
            index += 1
            continue
        if not option.startswith("-"):
            positional.append(option)
        index += 1

    if days is None and positional:
        days = int(positional[0])

    result = prune_checks(days)
    retention = settings.check_retention_days if days is None else days
    print(
        f"Deleted {int(result)} checks older than {retention} days "
        f"({getattr(result, 'records_created', 0)} budget rollups)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
