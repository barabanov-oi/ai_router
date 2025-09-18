"""Точка входа для запуска Flask-приложения и Telegram-бота."""

from __future__ import annotations

import logging
import os
from typing import Optional

from app import create_app, init_bot
from app.bot import start_bot_polling
from telebot import TeleBot

LOGGER = logging.getLogger(__name__)

app = create_app()


# AGENT: Запускает Flask-приложение и фоновые сервисы.
def main() -> None:
    """Инициализировать бота и запустить веб-сервер."""

    init_bot(app)
    bot: Optional[TeleBot] = getattr(app, "telegram_bot", None)
    start_bot_polling(bot)

    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    LOGGER.info("Запуск Flask-приложения на %s:%s", host, port)
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
