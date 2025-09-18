"""Service functions that manage application users."""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Dialog, DialogMessage, User

LOGGER = logging.getLogger(__name__)


def _now() -> _dt.datetime:
    # Комментарий для агентов: Вспомогательная функция обеспечивает единообразное вычисление времени в UTC.
    """Return current UTC time."""

    return _dt.datetime.utcnow()


def get_or_create_user(
    session: Session, telegram_id: int, username: Optional[str], full_name: Optional[str]
) -> User:
    # Комментарий для агентов: Сервис объединяет логику поиска пользователя и первичной регистрации.
    """Fetch existing user by Telegram ID or create a new record."""

    user = session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            last_seen_at=_now(),
        )
        session.add(user)
        session.flush()
        LOGGER.info("Создан новый пользователь %s", telegram_id)
    else:
        user.username = username
        user.full_name = full_name
        user.last_seen_at = _now()
    return user


def update_user_activity(session: Session, user: User) -> None:
    # Комментарий для агентов: Обновление активности полезно для метрик и фильтрации.
    """Update last activity timestamp for the provided user."""

    user.last_seen_at = _now()


def list_users(session: Session) -> Iterable[User]:
    # Комментарий для агентов: Возвращает коллекцию пользователей для отображения в админке.
    """Return iterable with all users sorted by creation time."""

    return session.scalars(select(User).order_by(User.created_at.desc())).all()


def toggle_user_access(session: Session, user_id: int) -> Optional[User]:
    # Комментарий для агентов: Позволяет администратору быстро блокировать или возвращать доступ.
    """Toggle user's active status and return updated instance."""

    user = session.get(User, user_id)
    if user is None:
        return None
    user.is_active = not user.is_active
    return user


def reset_active_dialogs(session: Session, user: User) -> None:
    # Комментарий для агентов: Функция завершает незакрытые диалоги, чтобы начать новый контекст.
    """Close all active dialogs for the specified user."""

    for dialog in session.scalars(
        select(Dialog).where(Dialog.user_id == user.id, Dialog.is_active.is_(True))
    ):
        dialog.is_active = False


def get_user_active_dialog(session: Session, user: User) -> Optional[Dialog]:
    # Комментарий для агентов: Используется для восстановления последнего диалога пользователя.
    """Return currently active dialog for the user."""

    return session.scalar(
        select(Dialog).where(Dialog.user_id == user.id, Dialog.is_active.is_(True))
    )


def create_dialog(session: Session, user: User, title: str) -> Dialog:
    # Комментарий для агентов: Создаёт новый диалог и помечает его активным.
    """Create a new dialog for the user with the provided title."""

    dialog = Dialog(user=user, title=title, is_active=True)
    session.add(dialog)
    session.flush()
    return dialog


def add_message(
    session: Session,
    dialog: Dialog,
    user: User,
    user_text: str,
    assistant_text: Optional[str],
    response_time_ms: Optional[int],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    total_tokens: Optional[int],
) -> DialogMessage:
    # Комментарий для агентов: Лог сохраняет пару запрос-ответ вместе с метриками для аналитики.
    """Persist new dialog message row with request and response data."""

    last_sequence = (
        session.scalar(
            select(func.max(DialogMessage.sequence_number)).where(
                DialogMessage.dialog_id == dialog.id
            )
        )
        or 0
    )
    next_sequence = last_sequence + 1
    message = DialogMessage(
        dialog=dialog,
        user=user,
        sequence_number=next_sequence,
        user_text=user_text,
        assistant_text=assistant_text,
        response_time_ms=response_time_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        assistant_sent_at=_now() if assistant_text else None,
    )
    session.add(message)
    session.flush()
    return message
