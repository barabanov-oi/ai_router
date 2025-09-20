"""Сервис управления Telegram-ботом."""

from __future__ import annotations

import threading
from typing import Optional

from flask import Flask
from telebot import TeleBot

from ..services.openai_service import OpenAIService
from ..services.settings_service import SettingsService
from .dialog_management import DialogManagementMixin
from .lifecycle import BotLifecycleMixin
from .message_handlers import MessageHandlingMixin


# NOTE[agent]: Класс инкапсулирует запуск бота, обработку команд и диалогов.
class TelegramBotManager(BotLifecycleMixin, MessageHandlingMixin, DialogManagementMixin):
    """Управляет жизненным циклом Telegram-бота и обработкой сообщений."""

    def __init__(self, app: Flask | None = None) -> None:
        """Подготавливает менеджер и вспомогательные сервисы."""

        self._settings = SettingsService()
        self._openai = OpenAIService()
        self._bot: Optional[TeleBot] = None
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._app: Flask | None = None
        if app is not None:
            self.init_app(app)
