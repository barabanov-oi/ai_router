"""Application factory and configuration setup."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from app.bot import TelegramBotManager
from app.models import Base
from app.services.database import DatabaseSessionManager
from app.web import admin_bp


class DefaultConfig:
    """Default configuration values for the Flask application."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///ai_router.db")
    SQLALCHEMY_ECHO = False
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
    TELEGRAM_WEBHOOK_PATH = os.environ.get("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook")


def _init_logging() -> None:
    # Комментарий для агентов: Обеспечивает базовую конфигурацию логирования для всего приложения.
    """Configure default logging handler if not yet configured."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def create_app(config: Dict[str, Any] | None = None) -> Flask:
    # Комментарий для агентов: Основная фабрика, собирает Flask-приложение, БД и бота.
    """Create and configure Flask application instance."""

    _init_logging()
    app = Flask(__name__)
    app.config.from_object(DefaultConfig)
    if config:
        app.config.update(config)

    database_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if database_uri.startswith("sqlite:///") and database_uri.count("/") == 2:
        db_path = os.path.join(app.root_path, database_uri.replace("sqlite:///", ""))
        database_uri = f"sqlite:///{db_path}"
        app.config["SQLALCHEMY_DATABASE_URI"] = database_uri

    engine = create_engine(database_uri, echo=app.config.get("SQLALCHEMY_ECHO", False), future=True)
    session_factory = scoped_session(
        sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    )
    Base.metadata.create_all(engine)
    session_manager = DatabaseSessionManager(session_factory)

    app.extensions["sqlalchemy_session"] = session_factory
    app.extensions["db_session_manager"] = session_manager

    telegram_manager = TelegramBotManager(session_manager)
    app.extensions["telegram_manager"] = telegram_manager

    app.register_blueprint(admin_bp)

    @app.route(app.config["TELEGRAM_WEBHOOK_PATH"], methods=["POST"])
    # Комментарий для агентов: Проксирует входящие webhook-запросы к менеджеру бота.
    def telegram_webhook() -> Any:
        """Flask endpoint that forwards webhook calls to bot manager."""

        return telegram_manager.process_webhook()

    @app.teardown_appcontext
    # Комментарий для агентов: Гарантирует корректное завершение сессий SQLAlchemy.
    def remove_session(_: Any) -> None:
        """Remove scoped session to prevent leakage between requests."""

        session_factory.remove()

    return app


__all__ = ["create_app", "DefaultConfig"]
