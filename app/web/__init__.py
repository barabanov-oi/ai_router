"""Пакет с веб-интерфейсами приложения."""

# NOTE[agent]: Экспортируем blueprints веб-интерфейса.
from .admin import admin_bp
from .webhook import telegram_webhook_bp

__all__ = ["admin_bp", "telegram_webhook_bp"]
