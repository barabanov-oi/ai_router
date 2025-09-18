"""Фабрика приложения Flask и базовая конфигурация."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from flask import Flask
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import ArgumentError

from .models import db


def _configure_logging(app: Flask) -> None:
    """Настраивает базовое логирование приложения."""
    # Для агентов: отдельная функция упрощает переиспользование и тестирование конфигурации логирования.
    logging.basicConfig(level=logging.INFO)
    app.logger.info("Логирование настроено на уровень INFO")


def _ensure_sqlite_directory(app: Flask) -> None:
    """Создаёт каталоги для SQLite, если они отсутствуют."""
    # Для агентов: проверяем только SQLite, чтобы не вмешиваться в другие диалекты БД.
    uri: str = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri:
        return

    try:
        url = make_url(uri)
    except ArgumentError:
        app.logger.warning("Некорректный URI базы данных: %s", uri)
        return

    if url.get_backend_name() != "sqlite":
        return

    database = url.database
    if not database or database == ":memory:":
        return

    db_path = Path(database).expanduser()
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        app.logger.error("Не удалось создать каталог для БД %s: %s", db_path, exc)
        raise


def create_app(config_path: Optional[str] = None) -> Flask:
    """Фабрика приложения Flask."""
    # Для агентов: фабрика позволяет легко конфигурировать приложение в тестах и проде.
    app = Flask(__name__, instance_relative_config=True)
    _configure_logging(app)

    default_db_path = Path(app.instance_path) / "ai_router.sqlite3"
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{default_db_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    if config_path:
        app.config.from_pyfile(config_path, silent=True)
    else:
        app.config.from_pyfile("config.py", silent=True)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    _ensure_sqlite_directory(app)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    return app
