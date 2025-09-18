"""Сервисы управления настройками приложения."""

from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from ..models import AdminSetting, ModelPreset, db

LOGGER = logging.getLogger(__name__)


# AGENT: Получает сохранённое значение настройки по ключу.
def get_setting(key: str) -> Optional[str]:
    """Получить значение настройки по указанному ключу.

    Args:
        key (str): Имя настройки.

    Returns:
        Optional[str]: Значение настройки или ``None``, если запись отсутствует.
    """

    setting = AdminSetting.query.filter_by(key=key).first()
    if setting:
        LOGGER.debug("Настройка %s получена из базы данных", key)
        return setting.value
    LOGGER.debug("Настройка %s не найдена", key)
    return None


# AGENT: Создаёт или обновляет настройку с указанным ключом.
def set_setting(key: str, value: str) -> None:
    """Сохранить значение настройки.

    Args:
        key (str): Имя настройки.
        value (str): Значение настройки.
    """

    try:
        setting = AdminSetting.query.filter_by(key=key).first()
        if setting:
            LOGGER.info("Обновление настройки %s", key)
            setting.value = value
        else:
            LOGGER.info("Создание новой настройки %s", key)
            setting = AdminSetting(key=key, value=value)
            db.session.add(setting)
        db.session.commit()
    except SQLAlchemyError as error:
        LOGGER.exception("Ошибка при сохранении настройки %s", key)
        db.session.rollback()
        raise RuntimeError(f"Не удалось сохранить настройку: {error}") from error


# AGENT: Читает ключ OpenAI из базы или переменных окружения.
def get_openai_api_key() -> Optional[str]:
    """Получить API-ключ OpenAI.

    Returns:
        Optional[str]: Ключ OpenAI из базы или переменной окружения ``OPENAI_API_KEY``.
    """

    value = get_setting("openai_api_key")
    if value:
        return value
    return os.getenv("OPENAI_API_KEY")


# AGENT: Убеждается, что в базе присутствуют предустановленные пресеты моделей.
def ensure_default_presets() -> None:
    """Создать базовые пресеты моделей, если они отсутствуют.

    Создаёт два режима работы: короткий и развёрнутый ответ.
    """

    if ModelPreset.query.count():
        LOGGER.debug("Пресеты моделей уже существуют, пропускаем инициализацию")
        return

    presets = [
        ModelPreset(
            name="concise",
            display_name="Краткий ответ",
            description="Сжатые ответы с акцентом на ключевые факты.",
            temperature=0.2,
            max_tokens=256,
            is_default=True,
        ),
        ModelPreset(
            name="detailed",
            display_name="Развёрнутый ответ",
            description="Подробные ответы с объяснениями и примерами.",
            temperature=0.8,
            max_tokens=768,
        ),
    ]
    db.session.add_all(presets)
    db.session.commit()
    LOGGER.info("Созданы пресеты моделей по умолчанию")


# AGENT: Определяет пресет по умолчанию для новых пользователей.
def get_default_preset() -> Optional[ModelPreset]:
    """Получить пресет модели по умолчанию.

    Returns:
        Optional[ModelPreset]: Пресет с флагом ``is_default`` или ``None``.
    """

    preset = ModelPreset.query.filter_by(is_default=True).first()
    if preset:
        return preset
    return ModelPreset.query.first()
