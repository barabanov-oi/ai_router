"""Пакет с веб-интерфейсами приложения."""

# NOTE[agent]: Экспортируем blueprint админки для удобного импорта.
from .admin import admin_bp

__all__ = ["admin_bp"]
