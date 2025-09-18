"""Инициализация Flask-приложения ai_router."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

from flask import Flask

from .bot import create_bot
from .models import db
from .services.settings_service import ensure_default_presets
from .web import admin_bp

LOGGER = logging.getLogger(__name__)


# AGENT: Создаёт и настраивает экземпляр Flask приложения.
def create_app() -> Flask:
    """Создать и сконфигурировать Flask-приложение."""

    app = Flask(__name__, instance_relative_config=False)
    configure_app(app)
    setup_logging(app)

    db.init_app(app)
    app.extensions["sqlalchemy_db"] = db

    with app.app_context():
        db.create_all()
        ensure_default_presets()

    register_blueprints(app)
    prepare_shell_context(app)

    app.telegram_bot = None  # type: ignore[attr-defined]
    return app


# AGENT: Настраивает основные параметры приложения и подключения к БД.
def configure_app(app: Flask) -> None:
    """Применить конфигурацию приложения из переменных окружения."""

    database_path = Path(os.getenv("DATABASE_PATH", "/workspace/ai_router/ai_router.db"))
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", os.getenv("DATABASE_URL", f"sqlite:///{database_path}"))
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    app.config.setdefault("SECRET_KEY", os.getenv("SECRET_KEY", "change-me"))
    app.config.setdefault("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN"))
    app.config.setdefault("ADMIN_SECRET", os.getenv("ADMIN_SECRET"))


# AGENT: Конфигурирует систему логирования приложения.
def setup_logging(app: Flask) -> None:
    """Настроить форматирование логов и их уровень."""

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app.logger.setLevel(log_level)
    LOGGER.info("Логирование настроено на уровень %s", log_level)


# AGENT: Регистрирует все необходимые Blueprint'ы.
def register_blueprints(app: Flask) -> None:
    """Подключить модули веб-интерфейса к приложению."""

    app.register_blueprint(admin_bp, url_prefix="/admin")


# AGENT: Расширяет контекст оболочки Flask удобными объектами.
def prepare_shell_context(app: Flask) -> None:
    """Добавить модели и БД в контекст flask shell."""

    from .models import Conversation, ModelPreset, RequestLog, User

    def shell_context() -> Dict[str, Any]:
        """Вернуть объекты, доступные в `flask shell`."""

        return {
            "db": db,
            "User": User,
            "Conversation": Conversation,
            "ModelPreset": ModelPreset,
            "RequestLog": RequestLog,
        }

    app.shell_context_processor(shell_context)


# AGENT: Создаёт экземпляр телеграм-бота для использования в приложении.
def init_bot(app: Flask) -> None:
    """Инициализировать телеграм-бота и сохранить в приложении."""

    bot = create_bot(app)
    app.telegram_bot = bot  # type: ignore[attr-defined]
