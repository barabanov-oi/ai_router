"""Инкапсуляция вызовов OpenAI API."""

from __future__ import annotations

import json
import re
from typing import Iterable

from openai import OpenAI
from flask import current_app

from ..models import MessageLog, db
from .settings_service import SettingsService


# NOTE[agent]: Класс служит для общения с OpenAI с учётом настроек приложения.
class OpenAIService:
    """Обеспечивает отправку сообщений в OpenAI Chat Completion API."""

    def __init__(self) -> None:
        """Инициализирует сервис и проверяет наличие API-ключа."""

        self._settings = SettingsService()

    # NOTE[agent]: Метод подготавливает сообщения и выполняет HTTP-запрос.
    def send_chat_request(self, messages: Iterable[dict[str, str]], model_config: dict) -> dict:
        """Отправляет запрос в OpenAI Chat Completion API.

        Args:
            messages: Последовательность сообщений в формате OpenAI.
            model_config: Параметры модели для запроса.

        Returns:
            Ответ API, преобразованный в словарь.
        """

        api_key = self._settings.get("openai_api_key")
        if not api_key:
            msg = "OpenAI API key is not configured"
            current_app.logger.error(msg)
            raise RuntimeError(msg)

        payload = {"messages": list(messages), **model_config}
        current_app.logger.debug("Запрос к OpenAI: %s", json.dumps({"payload": payload}, ensure_ascii=False))

        try:
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(**payload)
        except Exception as exc:  # pylint: disable=broad-except
            current_app.logger.exception("Ошибка при обращении к OpenAI")
            raise RuntimeError("Не удалось выполнить запрос к OpenAI") from exc

        data = response.model_dump()
        current_app.logger.debug("Ответ OpenAI: %s", json.dumps(data, ensure_ascii=False))
        return data

    # NOTE[agent]: Метод извлекает полезные данные из ответа OpenAI.
    def extract_message(self, data: dict, log_entry: MessageLog) -> str:
        """Извлекает текст ответа и количество токенов из ответа API.

        Args:
            data: Ответ OpenAI API.
            log_entry: Лог-запись, которую необходимо обновить.

        Returns:
            Текст ответа модели.
        """

        choices = data.get("choices", [])
        if not choices:
            current_app.logger.error("Ответ OpenAI не содержит вариантов")
            raise RuntimeError("Ответ OpenAI не содержит вариантов")
        message = self._strip_think_tags(choices[0]["message"].get("content"))
        usage = data.get("usage", {})
        tokens_used = int(usage.get("total_tokens", usage.get("completion_tokens", 0)))
        log_entry.register_response(message, tokens_used)
        db.session.commit()
        return message

    @staticmethod
    def _strip_think_tags(text: str | None) -> str:
        """Удаляет из ответа блоки вида <think>...</think>."""

        return re.sub(r"(?is)<think>.*?</think>", "", text or "").strip()
