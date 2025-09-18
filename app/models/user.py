"""Database models describing users of the application."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app import db


class User(db.Model):
    """Persistent information about a Telegram user interacting with the bot."""

    # NOTE(agents): SQLAlchemy automatically maps this class to the "users" table.
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String(64), unique=True, nullable=False)
    username = Column(String(255))
    full_name = Column(String(255))
    role = Column(String(32), default="user", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    current_mode = Column(String(64), default="concise", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        """Return a developer friendly representation of the model."""

        # NOTE(agents): Returning descriptive repr helps during debugging of admin utilities.
        return f"<User id={self.id} telegram_id={self.telegram_id} active={self.is_active}>"
