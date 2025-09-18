"""Service layer responsible for user management operations."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import User


# NOTE(agents): get_or_create_user links Telegram identities with persistent User records.
def get_or_create_user(telegram_id: str, username: Optional[str], full_name: Optional[str]) -> User:
    """Fetch existing user or create a new one based on Telegram identifiers."""

    user = User.query.filter_by(telegram_id=telegram_id).first()
    if user:
        user.username = username or user.username
        user.full_name = full_name or user.full_name
    else:
        user = User(telegram_id=telegram_id, username=username, full_name=full_name)
        db.session.add(user)
    user.last_seen = datetime.utcnow()
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        logging.exception("Failed to get or create user: %s", exc)
        db.session.rollback()
        raise
    return user


# NOTE(agents): update_last_seen refreshes the timestamp used in analytics and access control.
def update_last_seen(user: User) -> None:
    """Persist the fact that the user interacted with the system just now."""

    user.last_seen = datetime.utcnow()
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        logging.exception("Failed to update last_seen for user %s: %s", user.id, exc)
        db.session.rollback()
        raise


# NOTE(agents): set_user_active allows administrators to disable or enable bot access.
def set_user_active(user: User, is_active: bool) -> None:
    """Toggle user active state to control access to the Telegram bot."""

    user.is_active = is_active
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        logging.exception("Failed to toggle user %s active state: %s", user.id, exc)
        db.session.rollback()
        raise


# NOTE(agents): update_user_mode stores the last selected dialogue mode for subsequent messages.
def update_user_mode(user: User, mode: str) -> None:
    """Persist the preferred response mode for the given user."""

    user.current_mode = mode
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        logging.exception("Failed to update mode for user %s: %s", user.id, exc)
        db.session.rollback()
        raise


# NOTE(agents): list_users is leveraged in the admin UI for management pages.
def list_users() -> List[User]:
    """Return all users sorted by creation date descending."""

    return User.query.order_by(User.created_at.desc()).all()


# NOTE(agents): find_user provides convenience for admin detail pages and APIs.
def find_user(user_id: int) -> Optional[User]:
    """Fetch a user by primary key or return ``None`` if missing."""

    return User.query.filter_by(id=user_id).first()
