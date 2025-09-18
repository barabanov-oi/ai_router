"""Инициализация Flask-приложения."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from flask import Flask

from .models import db, AppSetting, ModelConfig
from .services.bot_service import TelegramBotManager


# NOTE[agent]: Функция создаёт и настраивает экземпляр приложения Flask.
def create_app(config: dict[str, Any] | None = None) -> Flask:
    """Создаёт экземпляр Flask и регистрирует все компоненты.

    Args:
        config: Дополнительные настройки, которые будут наложены на стандартные.

    Returns:
        Настроенный экземпляр Flask-приложения.
    """

    app = Flask(__name__, instance_relative_config=True)

    default_db_path = os.environ.get("AI_ROUTER_DB", "sqlite:///" + str(Path(app.instance_path) / "ai_router.sqlite"))
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("AI_ROUTER_SECRET", "development-secret"),
        SQLALCHEMY_DATABASE_URI=default_db_path,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TELEGRAM_WEBHOOK_HOST=os.environ.get("AI_ROUTER_WEBHOOK_HOST", ""),
    )

    if config:
        app.config.update(config)

    _configure_logging(app)
    _ensure_instance_folder(app)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        _ensure_default_settings()
        _ensure_default_model()

    _register_blueprints(app)

    app.extensions["bot_manager"] = TelegramBotManager()

    return app


# NOTE[agent]: Вспомогательная функция настраивает логирование приложения.
def _configure_logging(app: Flask) -> None:
    """Настраивает файловый и консольный логгеры."""

    log_level = os.environ.get("AI_ROUTER_LOG_LEVEL", "INFO").upper()
    app.logger.setLevel(getattr(logging, log_level, logging.INFO))

    if not app.logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(app.logger.level)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        stream_handler.setFormatter(formatter)
        app.logger.addHandler(stream_handler)

    log_directory = Path("logs")
    log_directory.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(log_directory / "app.log", maxBytes=1_000_000, backupCount=5)
    file_handler.setLevel(app.logger.level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    app.logger.addHandler(file_handler)


# NOTE[agent]: Функция гарантирует наличие папки instance для базы данных.
def _ensure_instance_folder(app: Flask) -> None:
    """Создаёт директорию instance, если она отсутствует."""

    try:
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    except OSError:
        app.logger.exception("Не удалось создать директорию instance")


# NOTE[agent]: Настройки по умолчанию создаются при первом запуске.
def _ensure_default_settings() -> None:
    """Создаёт базовые настройки, если они отсутствуют в базе."""

    defaults = {
        "openai_api_key": "",
        "default_mode": "default",
        "telegram_bot_token": "",
        "webhook_url": "",
        "webhook_secret": "",
        "active_model_id": "",
    }

    for key, value in defaults.items():
        setting = AppSetting.query.filter_by(key=key).first()
        if not setting:
            setting = AppSetting(key=key, value=value)
            db.session.add(setting)
    db.session.commit()


# NOTE[agent]: Создаём типовую конфигурацию модели, чтобы система работала "из коробки".
def _ensure_default_model() -> None:
    """Гарантирует наличие хотя бы одной конфигурации модели в базе."""

    if ModelConfig.query.count() == 0:
        model = ModelConfig(
            name="gpt-3.5-turbo",
            model="gpt-3.5-turbo",
            temperature=1.0,
            max_tokens=512,
            is_default=True,
        )
        db.session.add(model)
        db.session.commit()
        default_setting = AppSetting.query.filter_by(key="active_model_id").first()
        if default_setting:
            default_setting.update_value(str(model.id))
            db.session.commit()


# NOTE[agent]: Регистрация blueprint'ов расширяет функциональность приложения.
def _register_blueprints(app: Flask) -> None:
    """Регистрирует веб-интерфейсы и API в приложении."""

    from .web.admin import admin_bp  # Импорт внутри функции для корректного порядка загрузки

    app.register_blueprint(admin_bp)
