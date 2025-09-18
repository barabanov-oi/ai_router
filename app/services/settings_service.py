"""Service helpers for working with runtime settings stored in the database."""

from __future__ import annotations

import logging
from typing import Dict, Optional

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import Setting

DEFAULT_SETTINGS: Dict[str, str] = {
    "openai_model": "gpt-3.5-turbo",
    "openai_temperature": "0.7",
    "openai_max_tokens": "512",
    "telegram_bot_token": "",
}


# NOTE(agents): ensure_default_settings seeds the database with baseline configuration values.
def ensure_default_settings() -> None:
    """Create missing settings rows and populate them with sane defaults."""

    for key, default_value in DEFAULT_SETTINGS.items():
        if get_setting(key) is None:
            db.session.add(Setting(key=key, value=default_value))
    if current_app.config.get("OPENAI_API_KEY"):
        set_setting("openai_api_key", current_app.config["OPENAI_API_KEY"])
    if current_app.config.get("TELEGRAM_BOT_TOKEN"):
        set_setting("telegram_bot_token", current_app.config["TELEGRAM_BOT_TOKEN"])
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        logging.exception("Failed to ensure default settings: %s", exc)
        db.session.rollback()


# NOTE(agents): get_setting fetches a configuration value while hiding database interaction from callers.
def get_setting(key: str) -> Optional[str]:
    """Return a setting value by key or ``None`` if missing."""

    setting = Setting.query.filter_by(key=key).first()
    return setting.value if setting else None


# NOTE(agents): set_setting updates or inserts a key-value pair atomically.
def set_setting(key: str, value: str) -> None:
    """Persist a configuration value, creating the row if needed."""

    setting = Setting.query.filter_by(key=key).first()
    if setting is None:
        setting = Setting(key=key, value=value)
        db.session.add(setting)
    else:
        setting.value = value
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        logging.exception("Failed to store setting '%s': %s", key, exc)
        db.session.rollback()
        raise


# NOTE(agents): get_openai_configuration centralises retrieval of parameters necessary for requests to OpenAI API.
def get_openai_configuration() -> Dict[str, str]:
    """Return a dictionary containing model parameters required to call OpenAI."""

    return {
        "api_key": get_setting("openai_api_key") or current_app.config.get("OPENAI_API_KEY"),
        "model": get_setting("openai_model") or DEFAULT_SETTINGS["openai_model"],
        "temperature": float(get_setting("openai_temperature") or DEFAULT_SETTINGS["openai_temperature"]),
        "max_tokens": int(get_setting("openai_max_tokens") or DEFAULT_SETTINGS["openai_max_tokens"]),
    }


# NOTE(agents): get_all_settings is used by the admin UI to display current configuration.
def get_all_settings() -> Dict[str, Optional[str]]:
    """Return all stored settings as a dictionary for display in the admin panel."""

    return {setting.key: setting.value for setting in Setting.query.order_by(Setting.key).all()}
