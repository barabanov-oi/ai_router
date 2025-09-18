"""Запуск и управление телеграм-ботом."""

from __future__ import annotations

import threading
from typing import Optional

from flask import current_app

from app.bot import create_bot
from app.services import settings


class BotRunner:
    """Управляет жизненным циклом телеграм-бота."""

    def __init__(self) -> None:
        self._bot = None
        self._thread: Optional[threading.Thread] = None
        self._mode: Optional[str] = None

    def _ensure_token(self) -> str:
        """Проверяет наличие токена бота и возвращает его."""

        token = settings.get_setting("telegram_bot_token")
        if not token:
            raise RuntimeError("Токен телеграм-бота не задан")
        return token

    def start_polling(self) -> None:
        """Запускает бота в режиме polling."""

        app = current_app._get_current_object()
        token = self._ensure_token()
        if self._thread and self._thread.is_alive():
            current_app.logger.info("Бот уже запущен в режиме %s", self._mode)
            return
        bot = create_bot(app, token)
        self._bot = bot
        self._mode = "polling"

        def _runner() -> None:
            with app.app_context():
                current_app.logger.info("Запуск бота в режиме polling")
                bot.infinity_polling()

        self._thread = threading.Thread(target=_runner, daemon=True)
        self._thread.start()

    def start_webhook(self) -> None:
        """Запускает бота в режиме webhook (эмуляция)."""

        app = current_app._get_current_object()
        token = self._ensure_token()
        if self._thread and self._thread.is_alive():
            current_app.logger.info("Бот уже запущен в режиме %s", self._mode)
            return
        bot = create_bot(app, token)
        self._bot = bot
        self._mode = "webhook"

        def _runner() -> None:
            with app.app_context():
                current_app.logger.info("Запуск бота в режиме webhook (эмуляция)")
                bot.infinity_polling(long_polling_timeout=20)

        self._thread = threading.Thread(target=_runner, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Останавливает бота, если он запущен."""

        if self._bot:
            current_app.logger.info("Остановка бота")
            try:
                self._bot.stop_polling()
            except Exception as exc:  # pylint: disable=broad-except
                current_app.logger.exception("Ошибка при остановке бота: %s", exc)
        self._bot = None
        self._thread = None
        self._mode = None

    def status(self) -> dict:
        """Возвращает текущий статус бота."""

        return {
            "mode": self._mode,
            "running": bool(self._thread and self._thread.is_alive()),
        }


bot_runner = BotRunner()
"""Глобальный объект для управления ботом."""
