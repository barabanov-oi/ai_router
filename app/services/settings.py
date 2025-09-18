"""Сервисы для работы с настройками приложения."""

from __future__ import annotations

from typing import Optional

from flask import current_app

from app.models import Setting, db


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Возвращает значение настройки по ключу."""

    setting = Setting.query.filter_by(key=key).one_or_none()
    if setting is None:
        current_app.logger.debug("Настройка %s не найдена, используется значение по умолчанию", key)
        return default
    return setting.value if setting.value is not None else default


def set_setting(key: str, value: Optional[str]) -> Setting:
    """Создаёт или обновляет настройку."""

    current_app.logger.info("Сохранение настройки %s", key)
    setting = Setting.query.filter_by(key=key).one_or_none()
    if setting is None:
        setting = Setting(key=key, value=value)
        db.session.add(setting)
    else:
        setting.value = value
    db.session.commit()
    return setting


def get_all_settings() -> dict[str, Optional[str]]:
    """Возвращает словарь всех настроек."""

    return {setting.key: setting.value for setting in Setting.query.all()}
