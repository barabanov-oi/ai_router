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
    """Обеспечивает отправку сообщений в OpenAI Responses API."""

    RESPONSES_URL = "https://api.openai.com/v1/responses"

    def __init__(self) -> None:
        """Инициализирует сервис и проверяет наличие API-ключа."""

        self._settings = SettingsService()

    # NOTE[agent]: Метод подготавливает сообщения и выполняет HTTP-запрос.
    def send_chat_request(self, messages: Iterable[dict[str, str]], model_config: dict) -> dict:
        """Отправляет запрос в OpenAI Responses API.

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

        formatted_messages = self._prepare_input_messages(messages)
        payload = {"input": formatted_messages}
        payload.update(self._adapt_model_config(model_config))
        current_app.logger.debug("Запрос к OpenAI: %s", json.dumps({"payload": payload}, ensure_ascii=False))

        try:
            response = requests.post(
                self.RESPONSES_URL,
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

        message = self._extract_text_from_output(data.get("output", []))
        if not message:
            current_app.logger.error("Ответ OpenAI не содержит текстового сообщения")
            raise RuntimeError("Ответ OpenAI не содержит текстового сообщения")
        usage = data.get("usage", {})
        tokens_used = int(usage.get("total_tokens", usage.get("completion_tokens", 0)))
        log_entry.register_response(message, tokens_used)
        db.session.commit()
        return message

    def _prepare_input_messages(self, messages: Iterable[dict[str, str]]) -> list[dict]:
        """Преобразует сообщения к формату Responses API.

        Args:
            messages: Последовательность сообщений в старом формате Chat API.

        Returns:
            Сообщения, подготовленные для передачи в Responses API.
        """

        prepared: list[dict] = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            prepared.append(
                {
                    "role": role,
                    "content": [
                        {
                            "type": "text",
                            "text": content,
                        }
                    ],
                }
            )
        return prepared

    def _adapt_model_config(self, config: dict) -> dict:
        """Переименовывает параметры модели под требования Responses API.

        Args:
            config: Оригинальные параметры модели.

        Returns:
            Обновлённый словарь параметров для запроса.
        """

        adapted: dict = {}
        for key, value in config.items():
            if value is None:
                continue
            if key == "max_tokens":
                adapted["max_output_tokens"] = value
                continue
            adapted[key] = value
        return adapted

    def _extract_text_from_output(self, output: Iterable[dict]) -> str:
        """Извлекает текстовый ответ из структуры Responses API.

        Args:
            output: Список элементов ответа Responses API.

        Returns:
            Собранный текст ответа модели.
        """

        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for piece in item.get("content", []):
                if not isinstance(piece, dict):
                    continue
                if piece.get("type") in {"output_text", "text"}:
                    text = piece.get("text")
                    if text:
                        parts.append(text)
        return "".join(parts).strip()
