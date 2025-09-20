"""Клиент для провайдеров Google AI (Gemini, Gemma)."""

from __future__ import annotations

from typing import Any, Iterable

from ...models import MessageLog
from .base import BaseProviderClient


# NOTE[agent]: Заглушка сообщает о неготовности интеграции.
class GoogleProviderClient(BaseProviderClient):
    """Представляет клиента Google AI. Пока недоступно."""

    # NOTE[agent]: Метод информирует о необходимости реализовать вызов API Google.
    def send_chat_request(self, *, messages: Iterable[dict[str, str]], model_config: dict[str, Any]) -> dict:
        """Сообщает об отсутствии интеграции с Google AI."""

        raise RuntimeError("Интеграция с Google AI пока не реализована")

    # NOTE[agent]: Метод сигнализирует о неготовности интеграции.
    def extract_message(self, *, data: dict, log_entry: MessageLog) -> str:
        """Сообщает об отсутствии интеграции с Google AI."""

        raise RuntimeError("Интеграция с Google AI пока не реализована")
