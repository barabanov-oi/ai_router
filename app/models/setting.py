"""Key-value settings stored in the database."""

from __future__ import annotations

from sqlalchemy import Column, Integer, String, Text

from app import db


class Setting(db.Model):
    """Simple key value store for runtime configurable options."""

    # NOTE(agents): Settings are stored as plain strings for maximum flexibility.
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(128), unique=True, nullable=False)
    value = Column(Text)

    def __repr__(self) -> str:
        """Return readable representation for debugging."""

        # NOTE(agents): Only display key to avoid leaking sensitive values such as API keys.
        return f"<Setting key={self.key}>"
