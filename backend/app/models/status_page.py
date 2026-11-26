"""A public page listing a chosen set of monitors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class StatusPage(Base, TimestampMixin):
    __tablename__ = "status_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    slug: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # Monitor ids, in the order they should appear. Kept as a list rather than
    # a join table: a status page is an ordered selection, not a relationship
    # with data of its own.
    monitor_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    published: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship(back_populates="status_pages")
