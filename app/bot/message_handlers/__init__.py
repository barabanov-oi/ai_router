"""Пакет с миксинами обработки сообщений Telegram-бота."""

from __future__ import annotations

from .commands import CommandHandlersMixin
from .dialog_management import DialogHistoryHandlersMixin
from .messaging import MessagingMixin
from .notifications import ErrorNotificationMixin
from .state import BotPauseStateMixin


class MessageHandlingMixin(
    CommandHandlersMixin,
    MessagingMixin,
    DialogHistoryHandlersMixin,
    ErrorNotificationMixin,
    BotPauseStateMixin,
):
    """Комбинирует обработку команд, сообщений и состояния бота."""


__all__ = ["MessageHandlingMixin"]
