"""Базовые абстракции клиентов LLM-провайдеров."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from ...models import MessageLog


# NOTE[agent]: Базовый класс описывает интерфейс взаимодействия с поставщиком LLM.
class BaseProviderClient(ABC):
    """Определяет контракт для клиентов LLM-провайдеров."""

    def __init__(self, api_key: str) -> None:
        """Сохраняет API-ключ для дальнейших запросов."""

        if not api_key:
            raise RuntimeError("API-ключ поставщика не настроен")
        self._api_key = api_key

    # NOTE[agent]: Метод выполняет запрос к чату поставщика.
    @abstractmethod
    def send_chat_request(self, *, messages: Iterable[dict[str, str]], model_config: dict[str, Any]) -> dict:
        """Отправляет сообщения в API провайдера и возвращает ответ."""

    # NOTE[agent]: Метод извлекает полезные данные из ответа провайдера.
    @abstractmethod
    def extract_message(self, *, data: dict, log_entry: MessageLog) -> str:
        """Возвращает текст ответа и обновляет лог сообщения."""
