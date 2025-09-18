"""Models describing dialog sessions and contextual history."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app import db


class DialogSession(db.Model):
    """Long lived dialog session storing serialized history for a user."""

    # NOTE(agents): Each session represents a continuous conversation until reset by the user.
    __tablename__ = "dialog_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    mode = Column(String(64), default="concise", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    history = Column(Text, default="[]", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", backref="dialog_sessions")

    def __repr__(self) -> str:
        """Return a concise representation for debugging purposes."""

        # NOTE(agents): Showing active flag aids when inspecting sessions from admin tools.
        return f"<DialogSession id={self.id} user_id={self.user_id} active={self.is_active}>"
