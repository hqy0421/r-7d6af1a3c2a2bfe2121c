"""Authentication and ownership."""

from __future__ import annotations

from fastapi import Depends, Path, Request, status
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.core.security import SESSION_COOKIE_NAME, read_access_token
from app.db.session import get_db
from app.models import Monitor, User

UNAUTHENTICATED = APIError(
    "unauthenticated", "Sign in to continue.", status.HTTP_401_UNAUTHORIZED
)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise UNAUTHENTICATED
    payload = read_access_token(token)
    if not payload:
        raise UNAUTHENTICATED
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise UNAUTHENTICATED
    return user


def get_owned_monitor(
    monitor_id: int = Path(ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Monitor:
    """A monitor the caller owns, or 404 — never a hint that it exists."""
    monitor = db.get(Monitor, monitor_id)
    if monitor is None or monitor.user_id != user.id:
        raise APIError("not_found", "Monitor not found.", status.HTTP_404_NOT_FOUND)
    return monitor
