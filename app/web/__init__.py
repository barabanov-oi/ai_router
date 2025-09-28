"""Пакет с веб-интерфейсами приложения."""

# NOTE[agent]: Экспортируем blueprint админки и webhook для удобного импорта.
from .admin import admin_bp
from .telegram_webhook import register_telegram_webhook_route, telegram_webhook_bp

__all__ = ["admin_bp", "telegram_webhook_bp", "register_telegram_webhook_route"]
