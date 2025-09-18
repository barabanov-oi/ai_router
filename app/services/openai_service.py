"""Инкапсуляция вызовов OpenAI API."""

from __future__ import annotations

import json
from typing import Iterable

import requests
from flask import current_app

from ..models import MessageLog, db
from .settings_service import SettingsService


# NOTE[agent]: Класс служит для общения с OpenAI с учётом настроек приложения.
class OpenAIService:
    """Обеспечивает отправку сообщений в OpenAI Chat Completion API."""

    CHAT_URL = "https://api.openai.com/v1/chat/completions"
    DEFAULT_MODEL = "gpt-4o-mini"
    # NOTE[agent]: Сопоставление устаревших моделей с поддерживаемыми аналогами.
    MODEL_REPLACEMENTS = {
        "gpt-3.5-turbo": DEFAULT_MODEL,
        "gpt-3.5-turbo-0125": DEFAULT_MODEL,
        "gpt-3.5-turbo-1106": DEFAULT_MODEL,
        "gpt-3.5-turbo-16k": DEFAULT_MODEL,
        "gpt-3.5-turbo-instruct": DEFAULT_MODEL,
        "gpt-3.5-turbo-0301": DEFAULT_MODEL,
    }

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

        payload = {
            "messages": list(messages),
        }
        payload.update(model_config)

        model_name = payload.get("model")
        if not model_name:
            payload["model"] = self.DEFAULT_MODEL
            model_name = self.DEFAULT_MODEL
        replacement = self.MODEL_REPLACEMENTS.get(model_name)
        if replacement and replacement != model_name:
            current_app.logger.warning(
                "Модель %s недоступна, будет использована %s", model_name, replacement
            )
            payload["model"] = replacement

        current_app.logger.debug("Запрос к OpenAI: %s", json.dumps({"payload": payload}, ensure_ascii=False))

        try:
            response = requests.post(
                self.CHAT_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            current_app.logger.exception("Ошибка при обращении к OpenAI")
            raise RuntimeError("Не удалось выполнить запрос к OpenAI") from exc
        data = response.json()
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
        message = choices[0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_used = int(usage.get("total_tokens", usage.get("completion_tokens", 0)))
        log_entry.register_response(message, tokens_used)
        db.session.commit()
        return message
