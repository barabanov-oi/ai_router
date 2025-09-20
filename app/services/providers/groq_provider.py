"""Клиент для Groq (DeepSeek, Groq, Llama, OpenAI)."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from ...models import MessageLog
from .base import BaseProviderClient


# NOTE[agent]: Заглушка уведомляет об отсутствии готовой интеграции.
class GroqProviderClient(BaseProviderClient):
    """Представляет клиента Groq. Пока недоступно."""

    # NOTE[agent]: Метод информирует о необходимости реализовать вызов API Groq.
    def send_chat_request(
        self,
        *,
        messages: Iterable[Dict[str, str]],
        model_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Сообщает об отсутствии интеграции с Groq."""

        raise RuntimeError("Интеграция с Groq пока не реализована")

    # NOTE[agent]: Метод сигнализирует о неготовности интеграции.
    def extract_message(self, *, data: Dict[str, Any], log_entry: MessageLog) -> str:
        """Сообщает об отсутствии интеграции с Groq."""

        raise RuntimeError("Интеграция с Groq пока не реализована")
