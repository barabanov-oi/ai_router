"""Пакет моделей приложения."""

from flask_sqlalchemy import SQLAlchemy

#: Экземпляр SQLAlchemy, доступный всем модулям приложения.
db = SQLAlchemy()

__all__ = ["db"]
