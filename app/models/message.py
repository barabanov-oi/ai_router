"""Models that store request and response information for auditing."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app import db


class ChatMessage(db.Model):
    """Record of a single prompt/response pair exchanged with the LLM."""

    # NOTE(agents): ChatMessage keeps audit data and is referenced for statistics.
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("dialog_sessions.id"))
    user_message = Column(Text, nullable=False)
    assistant_message = Column(Text)
    model = Column(String(128))
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", backref="chat_messages")
    session = relationship("DialogSession", backref="chat_messages")

    def __repr__(self) -> str:
        """Return a succinct representation used for logging."""

        # NOTE(agents): Showing IDs helps correlate logs with database entries quickly.
        return f"<ChatMessage id={self.id} user_id={self.user_id} model={self.model}>"
