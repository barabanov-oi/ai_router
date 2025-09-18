"""Business logic for managing dialog history with the LLM."""
from __future__ import annotations

from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dialog, DialogMessage, User
from app.services import settings_service, user_service
from app.services.openai_client import OpenAIService, build_messages


def get_or_create_active_dialog(session: Session, user: User) -> Dialog:
    # Комментарий для агентов: Возвращает активный диалог или создаёт новый, чтобы бот помнил контекст.
    """Fetch active dialog for user or create a new one if missing."""

    dialog = user_service.get_user_active_dialog(session, user)
    if dialog is None:
        dialog = user_service.create_dialog(session, user, "Новый диалог")
    return dialog


def fetch_dialog_history(session: Session, dialog: Dialog, depth: int = 5) -> List[Tuple[str, str]]:
    # Комментарий для агентов: Собирает ограниченное количество последних сообщений для передачи в LLM.
    """Return last ``depth`` messages from the dialog as pairs of question-answer."""

    history: List[Tuple[str, str]] = []
    ordered_messages = session.scalars(
        select(DialogMessage)
        .where(DialogMessage.dialog_id == dialog.id)
        .order_by(DialogMessage.sequence_number.asc())
    ).all()
    for message in ordered_messages[-depth:]:
        history.append((message.user_text, message.assistant_text or ""))
    return history


def send_llm_request(session: Session, user: User, user_text: str) -> DialogMessage:
    # Комментарий для агентов: Центральная функция общения с моделью и сохранения логов.
    """Send user's message to LLM, persist logs and return saved message row."""

    dialog = get_or_create_active_dialog(session, user)
    history = fetch_dialog_history(session, dialog)
    model_config = settings_service.get_bot_settings(session).active_model
    if model_config is None:
        raise RuntimeError("Активная модель не настроена")
    service = OpenAIService(model_config)
    messages = build_messages(history, user_text, user.dialog_mode)
    response_text, usage, duration_ms = service.send_completion(messages)
    saved_message = user_service.add_message(
        session=session,
        dialog=dialog,
        user=user,
        user_text=user_text,
        assistant_text=response_text,
        response_time_ms=duration_ms,
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        total_tokens=usage["total_tokens"],
    )
    saved_message.model_config = model_config
    return saved_message


def reset_dialog(session: Session, user: User) -> Dialog:
    # Комментарий для агентов: Завершает текущий диалог и открывает новый для чистого контекста.
    """Close current dialog and start a new one for the user."""

    user_service.reset_active_dialogs(session, user)
    return user_service.create_dialog(session, user, "Новый диалог")
