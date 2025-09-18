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
    RESPONSES_URL = "https://api.openai.com/v1/responses"

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

        endpoint = self._pick_endpoint_for_model(model_config)
        messages_list = list(messages)
        if endpoint == "responses":
            payload = self._build_responses_payload(messages_list, model_config)
            current_app.logger.debug(
                "Запрос к OpenAI (responses): %s", json.dumps({"payload": payload}, ensure_ascii=False)
            )
            data = self._call_responses_api(payload, api_key)
        else:
            payload = self._build_chat_payload(messages_list, model_config)
            current_app.logger.debug(
                "Запрос к OpenAI (chat): %s", json.dumps({"payload": payload}, ensure_ascii=False)
            )
            data = self._call_chat_api(payload, api_key)
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
        if choices:
            message = choices[0]["message"]["content"]
            usage = data.get("usage", {})
            tokens_used = int(usage.get("total_tokens", usage.get("completion_tokens", 0)))
            log_entry.register_response(message, tokens_used)
            db.session.commit()
            return message

        message = self._extract_text_from_response(data)
        if message:
            usage = data.get("usage", {})
            tokens_used = int(
                usage.get(
                    "total_tokens",
                    usage.get("output_tokens", usage.get("completion_tokens", 0)),
                )
            )
            log_entry.register_response(message, tokens_used)
            db.session.commit()
            return message

        current_app.logger.error("Ответ OpenAI не содержит вариантов")
        raise RuntimeError("Ответ OpenAI не содержит вариантов")

    # NOTE[agent]: Метод определяет подходящий API-эндпойнт для модели.
    def _pick_endpoint_for_model(self, model_config: dict) -> str:
        """Возвращает тип эндпойнта (chat/responses) для указанной модели."""

        endpoint = str(model_config.get("endpoint", "")).strip().lower()
        if endpoint in {"chat", "responses"}:
            return endpoint

        model_name = str(model_config.get("model", "")).lower()
        responses_prefixes = ("gpt-4.1", "gpt-4o", "o4", "o3", "o1")
        if any(model_name.startswith(prefix) for prefix in responses_prefixes):
            return "responses"
        return "chat"

    # NOTE[agent]: Метод формирует payload для Chat Completions API.
    def _build_chat_payload(self, messages: Iterable[dict[str, str]], model_config: dict) -> dict:
        """Создаёт тело запроса для эндпойнта chat/completions."""

        model_name = model_config.get("model")
        if not model_name:
            raise RuntimeError("В конфигурации модели отсутствует параметр model")
        payload: dict[str, object] = {"model": model_name, "messages": list(messages)}
        for param in ("temperature", "top_p"):
            value = model_config.get(param)
            if value is not None:
                payload[param] = value
        return payload

    # NOTE[agent]: Метод подготавливает тело запроса для Responses API.
    def _build_responses_payload(self, messages: Iterable[dict[str, str]], model_config: dict) -> dict:
        """Создаёт payload для эндпойнта /v1/responses."""

        model_name = model_config.get("model")
        if not model_name:
            raise RuntimeError("В конфигурации модели отсутствует параметр model")

        prepared_messages = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            prepared_messages.append(
                {
                    "role": role,
                    "content": [
                        {
                            "type": "input_text",
                            "text": content if isinstance(content, str) else str(content),
                        }
                    ],
                }
            )

        payload: dict[str, object] = {
            "model": model_name,
            "input": prepared_messages,
        }
        for param in ("temperature", "top_p"):
            value = model_config.get(param)
            if value is not None:
                payload[param] = value
        return payload

    # NOTE[agent]: Метод выполняет HTTP-запрос к Chat Completions API.
    def _call_chat_api(self, payload: dict, api_key: str) -> dict:
        """Отправляет данные в эндпойнт chat/completions и возвращает ответ."""

        return self._perform_request(self.CHAT_URL, payload, api_key)

    # NOTE[agent]: Метод выполняет HTTP-запрос к Responses API.
    def _call_responses_api(self, payload: dict, api_key: str) -> dict:
        """Отправляет данные в эндпойнт /v1/responses и возвращает ответ."""

        return self._perform_request(self.RESPONSES_URL, payload, api_key)

    # NOTE[agent]: Общий метод отправки POST-запросов к OpenAI API.
    def _perform_request(self, url: str, payload: dict, api_key: str) -> dict:
        """Выполняет POST-запрос к указанному URL OpenAI и возвращает JSON."""

        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            current_app.logger.exception("Ошибка при обращении к OpenAI")
            raise RuntimeError("Не удалось выполнить запрос к OpenAI") from exc
        return response.json()

    # NOTE[agent]: Метод извлекает текст ответа из формата Responses API.
    def _extract_text_from_response(self, data: dict) -> str:
        """Преобразует ответ Responses API в строку."""

        output_blocks = data.get("output", [])
        collected_parts: list[str] = []

        for block in output_blocks:
            if not isinstance(block, dict):
                continue
            content_items = block.get("content", [])
            for item in content_items:
                if not isinstance(item, dict):
                    continue
                text_value = item.get("text")
                if item.get("type") in {"text", "output_text"} and isinstance(text_value, str):
                    collected_parts.append(text_value)
                    continue
                value = item.get("value")
                if isinstance(value, str):
                    collected_parts.append(value)

        if collected_parts:
            return "\n".join(part for part in collected_parts if part).strip()

        content_items = data.get("content", [])
        for item in content_items:
            if not isinstance(item, dict):
                continue
            text_value = item.get("text")
            if isinstance(text_value, str):
                collected_parts.append(text_value)
            value = item.get("value")
            if isinstance(value, str):
                collected_parts.append(value)

        return "\n".join(part for part in collected_parts if part).strip()
