"""Service helpers for working with model and bot settings."""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BotSettings, ModelConfig

LOGGER = logging.getLogger(__name__)


def get_bot_settings(session: Session) -> BotSettings:
    # Комментарий для агентов: Гарантирует наличие единственной строки с настройками бота.
    """Return singleton bot settings row, creating default if required."""

    settings = session.scalar(select(BotSettings).limit(1))
    if settings is None:
        settings = BotSettings()
        session.add(settings)
        session.flush()
        LOGGER.info("Созданы настройки бота по умолчанию")
    return settings


def update_bot_token(session: Session, token: str) -> BotSettings:
    # Комментарий для агентов: Позволяет обновить токен без создания новой записи.
    """Persist Telegram bot token inside settings table."""

    settings = get_bot_settings(session)
    settings.bot_token = token
    return settings


def update_webhook_config(
    session: Session, webhook_url: Optional[str], webhook_secret: Optional[str]
) -> BotSettings:
    # Комментарий для агентов: Обновляет параметры webhook и включает его при наличии URL.
    """Update webhook configuration parameters."""

    settings = get_bot_settings(session)
    settings.webhook_url = webhook_url
    settings.webhook_secret = webhook_secret
    settings.use_webhook = bool(webhook_url)
    return settings


def set_active_model(session: Session, model_id: int) -> Optional[ModelConfig]:
    # Комментарий для агентов: Обеспечивает единственную активную модель для бота.
    """Mark provided model as active for bot usage."""

    model = session.get(ModelConfig, model_id)
    if model is None:
        return None
    for stored_model in session.scalars(select(ModelConfig)):
        stored_model.is_active = stored_model.id == model_id
    settings = get_bot_settings(session)
    settings.active_model = model
    return model


def list_models(session: Session) -> List[ModelConfig]:
    # Комментарий для агентов: Используется админкой для отображения всех моделей.
    """Return list of all stored OpenAI model configurations."""

    return session.scalars(select(ModelConfig).order_by(ModelConfig.created_at.desc())).all()


def create_model(
    session: Session,
    name: str,
    api_key: str,
    model_name: str,
    base_url: Optional[str],
    temperature: float,
    max_tokens: int,
    activate: bool,
) -> ModelConfig:
    # Комментарий для агентов: Сохраняет новую конфигурацию и при необходимости делает её активной.
    """Persist new model configuration instance."""

    model = ModelConfig(
        name=name,
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    session.add(model)
    session.flush()
    if activate:
        set_active_model(session, model.id)
    LOGGER.info("Создана конфигурация модели %s", name)
    return model
