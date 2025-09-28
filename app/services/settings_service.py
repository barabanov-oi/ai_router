"""Сервис управления настройками приложения."""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlparse

from flask import current_app

from ..models import AppSetting, db


# NOTE[agent]: Класс инкапсулирует всю работу с таблицей настроек.
class SettingsService:
    """Сервисный класс для чтения и изменения настроек."""

    def __init__(self) -> None:
        """Подготавливает сервис к работе."""

    # NOTE[agent]: Метод возвращает значение настройки или значение по умолчанию.
    def get(self, key: str, default: Optional[str] = None) -> str:
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

    # NOTE[agent]: Метод возвращает целочисленное значение настройки.
    def get_int(self, key: str, default: Optional[int] = None) -> Optional[int]:
        """Преобразует значение настройки к целому числу.

        Args:
            key: Ключ искомой настройки.
            default: Значение по умолчанию, если ключ отсутствует или не преобразуется.

        Returns:
            Целочисленное значение настройки или default, если преобразование невозможно.
        """

        setting = AppSetting.query.filter_by(key=key).first()
        if not setting or setting.value is None or setting.value == "":
            return default
        try:
            return int(setting.value)
        except (TypeError, ValueError):
            current_app.logger.warning(
                "Настройка %s имеет некорректное числовое значение: %s",
                key,
                setting.value,
            )
            return default

    def get_webhook_path(self, *, fallback: str = "/bot/webhook") -> str:
        """Возвращает относительный путь webhook с учётом настроек."""

        raw_path = (self.get("webhook_path", "") or "").strip()
        if raw_path:
            return "/" + raw_path.lstrip("/")

        webhook_url = (self.get("webhook_url", "") or "").strip()
        if webhook_url:
            parsed = urlparse(webhook_url)
            if parsed.path:
                return "/" + parsed.path.lstrip("/")

        return fallback

    # NOTE[agent]: Метод возвращает множество всех настроек.
    def all_settings(self) -> Dict[str, str]:
        """Возвращает все настройки в виде словаря."""

        items = AppSetting.query.all()
        return {item.key: item.value or "" for item in items}
