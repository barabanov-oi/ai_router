"""Application factory for the ai_router project."""

from __future__ import annotations

import logging
import os
from threading import Event, Thread
from typing import Optional

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Global database object shared across models
# NOTE(agents): db is instantiated here to be imported across modules without circular dependencies.
db = SQLAlchemy()

# NOTE(agents): _bot_thread_stop_event controls the lifecycle of the Telegram bot thread during shutdown.
_bot_thread_stop_event = Event()

# NOTE(agents): _bot_thread holds the reference to the running Telegram bot polling thread.
_bot_thread: Optional[Thread] = None


def _configure_logging() -> None:
    """Configure application level logging for the whole project."""

    # NOTE(agents): Logging is centralised to keep formatting consistent across modules.
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
    )


# NOTE(agents): create_app wires together Flask, SQLAlchemy, blueprints and the Telegram bot.
def create_app() -> Flask:
    """Create and configure the Flask application instance."""

    _configure_logging()
    app = Flask(__name__)
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", os.environ.get("DATABASE_URL", "sqlite:///ai_router.db"))
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    app.config.setdefault("SECRET_KEY", os.environ.get("SECRET_KEY", "change-me"))
    app.config.setdefault("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY"))
    app.config.setdefault("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN"))
    app.config.setdefault("START_TELEGRAM_BOT", os.environ.get("START_TELEGRAM_BOT", "true").lower() == "true")

    db.init_app(app)

    with app.app_context():
        # NOTE(agents): Importing models here ensures SQLAlchemy metadata is registered before table creation.
        from app.models import ChatMessage, DialogSession, Setting, User  # noqa: F401

        db.create_all()

        # NOTE(agents): Register the administrative blueprint providing the web UI.
        from app.web.routes import admin_bp

        app.register_blueprint(admin_bp, url_prefix="/admin")

        # NOTE(agents): Ensure default settings exist before services attempt to read them.
        from app.services import settings_service

        settings_service.ensure_default_settings()

        # NOTE(agents): Start Telegram bot polling in a background thread if enabled and configured.
        if app.config.get("START_TELEGRAM_BOT"):
            from app.bot.manager import init_bot

            init_bot(app, _bot_thread_stop_event)

    return app


# NOTE(agents): stop_bot gracefully stops the Telegram bot when the process is terminating.
def stop_bot() -> None:
    """Stop the Telegram bot polling thread if it is running."""

    global _bot_thread
    if _bot_thread and _bot_thread.is_alive():
        logging.info("Stopping Telegram bot thread")
        try:
            from app.bot.manager import stop_bot_polling

            stop_bot_polling()
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to stop Telegram bot gracefully: %s", exc)
        _bot_thread_stop_event.set()
        _bot_thread.join(timeout=5)
        _bot_thread = None
        _bot_thread_stop_event.clear()


# NOTE(agents): register_bot_thread exposes a way for the bot manager to store a reference to the polling thread.
def register_bot_thread(thread: Thread) -> None:
    """Register the global reference to the Telegram bot polling thread."""

    global _bot_thread
    _bot_thread = thread

