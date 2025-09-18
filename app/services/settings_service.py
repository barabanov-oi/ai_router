"""Сервис управления настройками приложения."""

from __future__ import annotations

from typing import Any

from flask import current_app

from ..models import AppSetting, db


# NOTE[agent]: Класс инкапсулирует всю работу с таблицей настроек.
class SettingsService:
    """Сервисный класс для чтения и изменения настроек."""

    def __init__(self) -> None:
        """Подготавливает сервис к работе."""

    # NOTE[agent]: Метод возвращает значение настройки или значение по умолчанию.
    def get(self, key: str, default: str | None = None) -> str:
        """Получает строковое значение настройки.

        Args:
            key: Ключ настройки.
            default: Значение по умолчанию, если настройка не найдена.

        Returns:
            Строковое значение настройки или default.
        """

        setting = AppSetting.query.filter_by(key=key).first()
        if setting:
            return setting.value or ""
        if default is not None:
            return default
        current_app.logger.warning("Настройка %s не найдена", key)
        return ""

    # NOTE[agent]: Метод сохраняет новое значение настройки.
    def set(self, key: str, value: Any) -> None:
        """Сохраняет значение настройки."""

        setting = AppSetting.query.filter_by(key=key).first()
        if not setting:
            setting = AppSetting(key=key, value=str(value))
            db.session.add(setting)
        else:
            setting.update_value(str(value))
        db.session.commit()

    # NOTE[agent]: Метод возвращает множество всех настроек.
    def all_settings(self) -> dict[str, str]:
        """Возвращает все настройки в виде словаря."""

        items = AppSetting.query.all()
        return {item.key: item.value or "" for item in items}
