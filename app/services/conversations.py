"""Сервисы управления диалогами и пользователями."""

from __future__ import annotations

from datetime import datetime
from typing import List

from flask import current_app

from app.models import Conversation, MessageLog, ModelConfig, User, db


def get_or_create_user(telegram_id: int, username: str | None = None) -> User:
    """Возвращает пользователя по Telegram ID или создаёт нового."""

    user = User.query.filter_by(telegram_id=str(telegram_id)).one_or_none()
    if user is None:
        current_app.logger.info("Создание нового пользователя %s", telegram_id)
        user = User(telegram_id=str(telegram_id), username=username)
        db.session.add(user)
        db.session.commit()
    if username and user.username != username:
        user.username = username
        db.session.commit()
    return user


def update_user_activity(user: User) -> None:
    """Обновляет время последней активности пользователя."""

    user.last_active_at = datetime.utcnow()
    db.session.commit()


def get_active_conversation(user: User, mode: str = "detailed") -> Conversation | None:
    """Возвращает активный диалог пользователя для указанного режима."""

    return (
        Conversation.query.filter_by(user_id=user.id, is_active=True, mode=mode)
        .order_by(Conversation.started_at.desc())
        .first()
    )


def start_new_conversation(
    user: User,
    model: ModelConfig | None,
    mode: str,
) -> Conversation:
    """Создаёт новый диалог и делает его активным."""

    current_app.logger.info(
        "Старт нового диалога: user=%s mode=%s model=%s",
        user.id,
        mode,
        model.id if model else None,
    )
    Conversation.query.filter_by(user_id=user.id, is_active=True, mode=mode).update(
        {Conversation.is_active: False, Conversation.ended_at: datetime.utcnow()}
    )
    conversation = Conversation(user=user, model=model, mode=mode, is_active=True)
    db.session.add(conversation)
    db.session.commit()
    return conversation


def append_message(
    conversation: Conversation,
    user: User,
    user_message: str,
    assistant_response: str | None,
    mode: str,
    token_usage: int | None = None,
) -> MessageLog:
    """Добавляет запись в лог сообщений."""

    next_index = (
        db.session.query(db.func.coalesce(db.func.max(MessageLog.message_index), 0) + 1)
        .filter(MessageLog.conversation_id == conversation.id)
        .scalar()
    )
    log_entry = MessageLog(
        conversation=conversation,
        user=user,
        message_index=next_index,
        user_message=user_message,
        assistant_response=assistant_response,
        response_timestamp=datetime.utcnow() if assistant_response else None,
        mode=mode,
        token_usage=token_usage,
    )
    db.session.add(log_entry)
    db.session.commit()
    return log_entry


def close_conversation(conversation: Conversation) -> None:
    """Завершает диалог пользователя."""

    conversation.is_active = False
    conversation.ended_at = datetime.utcnow()
    db.session.commit()


def fetch_conversation_history(conversation: Conversation) -> List[dict[str, str]]:
    """Возвращает историю сообщений для передачи в LLM."""

    messages: List[dict[str, str]] = []
    for message in MessageLog.query.filter_by(conversation_id=conversation.id).order_by(
        MessageLog.message_index
    ):
        messages.append({"role": "user", "content": message.user_message})
        if message.assistant_response:
            messages.append({"role": "assistant", "content": message.assistant_response})
    return messages
