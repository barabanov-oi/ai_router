"""Инициализация Flask-приложения."""

from __future__ import annotations

import io
import locale
import logging
import os
import sys
from logging import Handler
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from flask import Flask
from flask_migrate import Migrate
from sqlalchemy.exc import SQLAlchemyError

from .models import db, AppSetting, LLMProvider, ModelConfig
from .bot.bot_service import TelegramBotManager
from dotenv import load_dotenv


# Экземпляр мигратора (Alembic через Flask-Migrate).
migrate = Migrate(compare_type=True)


def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    """Создаёт экземпляр Flask и регистрирует все компоненты.

    Args:
        config: Дополнительные настройки, которые будут наложены на стандартные.

    Returns:
        Настроенный экземпляр Flask-приложения.
    """
    app = Flask(__name__, instance_relative_config=True)

    # РЕЖИМ ЗАПУСКА: normal | migrate
    # В режиме "migrate" мы не регистрируем blueprint'ы и не инициализируем бота,
    # чтобы можно было безопасно выполнить flask db upgrade при первом старте.
    BOOT_MODE = os.getenv("APP_BOOTSTRAP_MODE", "normal").lower()

    # Конфигурация по умолчанию; может быть переопределена через env и аргумент `config`.
    default_db_path = os.environ.get(
        "AI_ROUTER_DB",
        "sqlite:///" + str(Path(app.instance_path) / "ai_router.sqlite"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("AI_ROUTER_SECRET", "development-secret"),
        SQLALCHEMY_DATABASE_URI=default_db_path,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TELEGRAM_WEBHOOK_HOST=os.environ.get("AI_ROUTER_WEBHOOK_HOST", ""),
    )

    # Загружаем учётные данные админа из окружения или .env.
    admin_login, admin_password = _load_admin_credentials()
    app.config["ADMIN_LOGIN"] = admin_login
    app.config["ADMIN_PASSWORD"] = admin_password
    if not admin_login or not admin_password:
        app.logger.warning("Учётные данные администратора не заданы.")

    if config:
        app.config.update(config)

    _configure_logging(app)
    _ensure_instance_folder(app)

    # Инициализация БД и миграций.
    db.init_app(app)
    migrate.init_app(app, db)

    # Не вызываем db.create_all(); схему меняем через миграции.
    # Инициализацию дефолтных записей выполняем только если таблицы доступны.
    # with app.app_context():
    #     _try_seed_defaults(app)

    # ⚠️ Критично: не трогаем БД на этапе миграций (первый старт).
    if BOOT_MODE != "migrate":
        _register_blueprints(app)

        # Менеджер бота (может обращаться к настройкам) — только вне режима миграций.
        bot_manager = TelegramBotManager(app)
        app.extensions["bot_manager"] = bot_manager

    return app


def _load_admin_credentials() -> tuple[Optional[str], Optional[str]]:
    """Возвращает логин и пароль администратора из окружения или .env."""
    admin_login = os.environ.get("ADMLOGIN")
    admin_password = os.environ.get("ADMPWD")
    if admin_login and admin_password:
        return admin_login, admin_password

    # Если переменных нет — пытаемся загрузить их из файла .env.
    load_dotenv()
    admin_login = admin_login or os.environ.get("ADMLOGIN")
    admin_password = admin_password or os.environ.get("ADMPWD")
    return admin_login, admin_password


def _configure_logging(app: Flask) -> None:
    """Настраивает файловый и консольный логгеры."""
    log_level = os.environ.get("AI_ROUTER_LOG_LEVEL", "INFO").upper()
    app.logger.setLevel(getattr(logging, log_level, logging.INFO))

    preferred_encoding = _get_preferred_log_encoding()
    _configure_existing_handlers(app.logger.handlers, preferred_encoding, app.logger.level)

    if not app.logger.handlers:
        stream_handler = logging.StreamHandler(
            _ensure_stream_encoding(sys.stderr, preferred_encoding),
        )
        stream_handler.setLevel(app.logger.level)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        stream_handler.setFormatter(formatter)
        app.logger.addHandler(stream_handler)

    log_directory = Path("logs")
    log_directory.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(
        log_directory / "app.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding=preferred_encoding,
    )
    file_handler.setLevel(app.logger.level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    app.logger.addHandler(file_handler)


def _ensure_instance_folder(app: Flask) -> None:
    """Создаёт директорию instance, если она отсутствует."""
    try:
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    except OSError:
        app.logger.exception("Не удалось создать директорию instance")


def _try_seed_defaults(app: Flask) -> None:
    """Пытается создать базовые настройки и дефолтную модель, если таблицы уже существуют."""
    try:
        _ensure_default_settings()
        _ensure_default_provider()
        _ensure_default_model()
    except SQLAlchemyError as exc:
        # Таблицы могут быть ещё не созданы (до flask db upgrade).
        app.logger.warning("Пропущена инициализация дефолтных данных: %s", exc)


def _ensure_default_settings() -> None:
    """Создаёт базовые настройки, если они отсутствуют в базе."""
    defaults = {
        "default_mode": "default",
        "telegram_bot_token": "",
        "webhook_path": "",
        "webhook_url": "",
        "webhook_secret": "",
        "active_model_id": "",
    }

    created = False
    for key, value in defaults.items():
        setting = AppSetting.query.filter_by(key=key).first()
        if not setting:
            db.session.add(AppSetting(key=key, value=value))
            created = True
    if created:
        db.session.commit()


def _ensure_default_provider() -> LLMProvider:
    """Гарантирует наличие базового поставщика OpenAI."""
    provider = LLMProvider.query.filter_by(vendor=LLMProvider.VENDOR_OPENAI).first()
    if provider:
        return provider

    provider = LLMProvider(
        name="OpenAI (по умолчанию)",
        vendor=LLMProvider.VENDOR_OPENAI,
        api_key="",
    )
    db.session.add(provider)
    db.session.commit()
    return provider


def _ensure_default_model() -> None:
    """Гарантирует наличие хотя бы одной конфигурации модели в базе."""
    if ModelConfig.query.count() == 0:
        provider = _ensure_default_provider()
        # Поля подстраиваются под текущую схему ModelConfig.
        model = ModelConfig(
            name="gpt-3.5-turbo",
            model="gpt-3.5-turbo",
            provider=provider,
            temperature=1.0,
            max_tokens=512,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            system_instruction="Ты дружелюбный помощник.",
            is_default=True,
        )
        db.session.add(model)
        db.session.commit()

        default_setting = AppSetting.query.filter_by(key="active_model_id").first()
        if default_setting:
            try:
                default_setting.update_value(str(model.id))  # если у модели есть мутатор
            except AttributeError:
                default_setting.value = str(model.id)
            db.session.commit()


def _register_blueprints(app: Flask) -> None:
    """Регистрирует веб-интерфейсы и API в приложении."""
    from .services.settings_service import SettingsService
    from .web.admin import admin_bp  # Импорт внутри функции для корректного порядка загрузки
    from .web.telegram_webhook import (
        register_telegram_webhook_route,
        telegram_webhook_bp,
    )

    with app.app_context():
        settings_service = SettingsService()
        webhook_path = settings_service.get_webhook_path()

    register_telegram_webhook_route(webhook_path)
    app.register_blueprint(telegram_webhook_bp)
    app.register_blueprint(admin_bp)


def _get_preferred_log_encoding() -> str:
    """Определяет кодировку логов с учётом платформы и окружения."""
    override_encoding = os.environ.get("AI_ROUTER_LOG_ENCODING")
    if override_encoding:
        return override_encoding

    if os.name == "nt":
        stdout_encoding = getattr(sys.stdout, "encoding", None)
        if stdout_encoding:
            return stdout_encoding

        stderr_encoding = getattr(sys.stderr, "encoding", None)
        if stderr_encoding:
            return stderr_encoding

        locale_encoding = locale.getpreferredencoding(False)
        if locale_encoding:
            return locale_encoding

    return "utf-8"


def _configure_existing_handlers(handlers: List[Handler], encoding: str, level: int) -> None:
    """Обновляет кодировку потоковых обработчиков, созданных Flask ранее."""
    for handler in list(handlers):
        handler.setLevel(level)
        if isinstance(handler, logging.StreamHandler):
            stream = getattr(handler, "stream", None)
            if stream is not None:
                handler.setStream(_ensure_stream_encoding(stream, encoding))


def _ensure_stream_encoding(stream: TextIO, encoding: str) -> TextIO:
    """Гарантирует, что переданный поток поддерживает нужную кодировку."""
    current_encoding = getattr(stream, "encoding", None)
    if current_encoding and current_encoding.lower() == encoding.lower():
        return stream

    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding=encoding, errors="replace")
        return stream

    return _EncodingStreamWrapper(stream, encoding)


class _EncodingStreamWrapper(io.TextIOBase):
    """Оборачивает текстовый поток, принудительно перекодируя вывод."""

    def __init__(self, base_stream: TextIO, encoding: str, errors: str = "replace") -> None:
        self._base_stream = base_stream
        self._encoding = encoding
        self._errors = errors

    def write(self, s: str) -> int:  # type: ignore[override]
        if not isinstance(s, str):
            s = str(s)
        data = s.encode(self._encoding, errors=self._errors)
        buffer = getattr(self._base_stream, "buffer", None)
        if buffer is not None:
            buffer.write(data)
        else:
            text = data.decode(self._encoding, errors=self._errors)
            self._base_stream.write(text)
        return len(s)

    def flush(self) -> None:
        flush = getattr(self._base_stream, "flush", None)
        if callable(flush):
            flush()

    def close(self) -> None:  # type: ignore[override]
        self.flush()

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return self._encoding

    @property
    def errors(self) -> str:  # type: ignore[override]
        return self._errors
