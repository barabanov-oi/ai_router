"""Основная точка входа Flask-приложения."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from flask import Flask, redirect, url_for
from flask.logging import default_handler
from dotenv import load_dotenv

from app.models import ModelConfig, db
from app.services import settings as settings_service
from app.web import admin_bp

DEFAULT_DATABASE_URI = "sqlite:///ai_router.db"
"""База данных по умолчанию."""


def _configure_logging(app: Flask) -> None:
    """Настраивает логирование приложения."""

    app.logger.removeHandler(default_handler)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def create_app(config: Dict[str, Any] | None = None) -> Flask:
    """Создаёт и настраивает экземпляр Flask."""

    load_dotenv()
    app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", os.getenv("DATABASE_URL", DEFAULT_DATABASE_URI))
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    app.config.setdefault("SECRET_KEY", os.getenv("SECRET_KEY", "dev"))
    if config:
        app.config.update(config)

    db.init_app(app)
    _configure_logging(app)
    app.register_blueprint(admin_bp)

    @app.route("/")
    def index() -> Any:
        """Редирект на административный интерфейс."""

        return redirect(url_for("admin.dashboard"))

    with app.app_context():
        db.create_all()
        _ensure_default_settings()

    return app


def _ensure_default_settings() -> None:
    """Гарантирует наличие обязательных настроек."""

    settings_service.get_all_settings()
    default_model = ModelConfig.query.filter_by(is_default=True, is_active=True).first()
    if default_model:
        settings_service.set_setting("default_model_name", default_model.name)
