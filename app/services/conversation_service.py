"""Сервисы работы с пользователями и диалогами."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Iterable, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from ..models import Conversation, ModelPreset, RequestLog, User, db
from .settings_service import get_default_preset

LOGGER = logging.getLogger(__name__)


# AGENT: Гарантирует наличие пользователя в базе данных.
def get_or_create_user(telegram_id: str, username: Optional[str], full_name: str) -> User:
    """Получить существующего пользователя или создать нового.

    Args:
        telegram_id (str): Уникальный идентификатор пользователя в Telegram.
        username (Optional[str]): Имя пользователя Telegram.
        full_name (str): Отображаемое имя пользователя.

    Returns:
        User: ORM-объект пользователя.
    """

    user = User.query.filter_by(telegram_id=telegram_id).first()
    if user:
        LOGGER.debug("Найден существующий пользователь %s", telegram_id)
        if username and username != user.username:
            user.username = username
        if full_name and full_name != user.full_name:
            user.full_name = full_name
        db.session.commit()
        return user

    LOGGER.info("Создание нового пользователя %s", telegram_id)
    preset = get_default_preset()
    user = User(
        telegram_id=telegram_id,
        username=username,
        full_name=full_name,
        preferred_preset=preset,
        last_interaction=dt.datetime.utcnow(),
    )
    db.session.add(user)
    db.session.commit()
    return user


# AGENT: Обновляет время последнего взаимодействия пользователя.
def touch_user(user: User) -> None:
    """Обновить отметку последнего взаимодействия пользователя.

    Args:
        user (User): Пользователь, который взаимодействовал с ботом.
    """

    user.last_interaction = dt.datetime.utcnow()
    db.session.commit()


# AGENT: Находит активный диалог пользователя или создаёт новый.
def get_active_conversation(user: User) -> Conversation:
    """Получить текущий активный диалог пользователя.

    Args:
        user (User): Пользователь, для которого ищется диалог.

    Returns:
        Conversation: Активный диалог пользователя.
    """

    conversation = (
        Conversation.query.filter_by(user=user, is_active=True)
        .order_by(Conversation.created_at.desc())
        .first()
    )
    if conversation:
        LOGGER.debug("Используется активный диалог %s", conversation.id)
        return conversation

    title = f"Диалог от {dt.datetime.utcnow():%d.%m.%Y %H:%M}"
    preset = user.preferred_preset or get_default_preset()
    conversation = Conversation(title=title, user=user, preset=preset)
    db.session.add(conversation)
    db.session.commit()
    LOGGER.info("Создан новый диалог %s для пользователя %s", conversation.id, user.id)
    return conversation


# AGENT: Завершает активный диалог пользователя.
def close_conversation(conversation: Conversation) -> None:
    """Завершить указанный диалог.

    Args:
        conversation (Conversation): Диалог, который необходимо завершить.
    """

    conversation.is_active = False
    conversation.ended_at = dt.datetime.utcnow()
    db.session.commit()
    LOGGER.info("Диалог %s помечен как завершённый", conversation.id)


# AGENT: Сохраняет в базе новую запись лога запроса.
def log_request(
    user: User,
    conversation: Conversation,
    preset: Optional[ModelPreset],
    prompt: str,
    response: Optional[str],
    status: str,
    error_message: Optional[str] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
) -> RequestLog:
    """Создать запись о запросе пользователя.

    Args:
        user (User): Пользователь, отправивший запрос.
        conversation (Conversation): Диалог, в рамках которого произошёл запрос.
        preset (Optional[ModelPreset]): Использованный пресет.
        prompt (str): Текст запроса пользователя.
        response (Optional[str]): Ответ модели.
        status (str): Статус обработки (``success`` или ``error``).
        error_message (Optional[str]): Текст ошибки, если она произошла.
        prompt_tokens (Optional[int]): Количество токенов запроса.
        completion_tokens (Optional[int]): Количество токенов ответа.
        total_tokens (Optional[int]): Общее количество токенов.

    Returns:
        RequestLog: Сохранённая запись лога.
    """

    log_entry = RequestLog(
        user=user,
        conversation=conversation,
        preset=preset,
        prompt=prompt,
        response=response,
        status=status,
        error_message=error_message,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )
    db.session.add(log_entry)
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        LOGGER.exception("Не удалось сохранить лог запроса")
        db.session.rollback()
        raise RuntimeError("Ошибка сохранения лога запроса") from error
    return log_entry


# AGENT: Формирует список сообщений для передачи в OpenAI с учётом истории диалога.
def build_conversation_messages(
    conversation: Conversation, limit: int = 10
) -> List[dict[str, str]]:
    """Сформировать историю диалога в формате, пригодном для OpenAI.

    Args:
        conversation (Conversation): Диалог пользователя.
        limit (int): Максимальное количество последних сообщений.

    Returns:
        List[dict[str, str]]: Список сообщений с ролями ``user`` и ``assistant``.
    """

    logs: Iterable[RequestLog] = (
        conversation.logs.filter(RequestLog.status == "success")
        .order_by(RequestLog.created_at.desc())
        .limit(limit)
        .all()
    )
    messages: List[dict[str, str]] = []
    for log in reversed(list(logs)):
        if log.prompt:
            messages.append({"role": "user", "content": log.prompt})
        if log.response:
            messages.append({"role": "assistant", "content": log.response})
    return messages


# AGENT: Обновляет предпочтительный пресет пользователя.
def update_user_preset(user: User, preset: ModelPreset) -> None:
    """Сохранить выбранный пользователем пресет модели.

    Args:
        user (User): Пользователь, изменяющий режим работы модели.
        preset (ModelPreset): Выбранный пресет модели.
    """

    user.preferred_preset = preset
    db.session.commit()
    LOGGER.info("Пользователь %s выбрал пресет %s", user.id, preset.name)
