"""Utilities that manage dialog sessions and message history."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List

from app import db
from app.models import DialogSession, User

MAX_HISTORY_MESSAGES = 20


# NOTE(agents): ensure_active_session either reuses or creates a conversation context for a user.
def ensure_active_session(user: User, mode: str) -> DialogSession:
    """Return an active dialog session for the user and mode, creating it if necessary."""

    session = (
        DialogSession.query.filter_by(user_id=user.id, mode=mode, is_active=True)
        .order_by(DialogSession.updated_at.desc())
        .first()
    )
    if session is None:
        session = DialogSession(user_id=user.id, mode=mode)
        db.session.add(session)
        db.session.commit()
    return session


# NOTE(agents): reset_active_sessions terminates existing dialog contexts when the user starts anew.
def reset_active_sessions(user: User) -> None:
    """Mark all active dialog sessions for the user as inactive."""

    DialogSession.query.filter_by(user_id=user.id, is_active=True).update({"is_active": False}, synchronize_session=False)
    db.session.commit()


# NOTE(agents): load_history deserialises stored JSON into a list of role/content dictionaries.
def load_history(session: DialogSession) -> List[Dict[str, str]]:
    """Return the chat history for the session."""

    try:
        return json.loads(session.history or "[]")
    except json.JSONDecodeError:
        return []


# NOTE(agents): save_history persists the trimmed history and updates timestamps.
def save_history(session: DialogSession, history: List[Dict[str, str]]) -> None:
    """Serialize and store the provided chat history for the session."""

    trimmed_history = history[-MAX_HISTORY_MESSAGES:]
    session.history = json.dumps(trimmed_history)
    session.updated_at = datetime.utcnow()
    db.session.commit()


# NOTE(agents): append_message centralises the list mutation logic for uniformity.
def append_message(history: List[Dict[str, str]], role: str, content: str) -> List[Dict[str, str]]:
    """Return a new history list with the message appended."""

    new_history = list(history)
    new_history.append({"role": role, "content": content})
    return new_history
