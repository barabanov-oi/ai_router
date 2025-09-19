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
    """Обеспечивает отправку сообщений в OpenAI API."""

    CHAT_URL = "https://api.openai.com/v1/chat/completions"
    RESPONSES_URL = "https://api.openai.com/v1/responses"

    def __init__(self) -> None:
        """Инициализирует сервис и проверяет наличие API-ключа."""

        self._settings = SettingsService()

    # NOTE[agent]: Метод подготавливает сообщения и выполняет HTTP-запрос.
    def send_chat_request(self, messages: Iterable[dict[str, str]], model_config: dict) -> dict:
        """Отправляет запрос в OpenAI, выбирая подходящий эндпойнт.

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

        messages_list = list(messages)
        endpoint = self._pick_endpoint_for_model(model_config)
        if endpoint == "responses":
            payload = self._build_responses_payload(messages_list, model_config)
            return self._call_responses_api(payload, api_key)
        payload = self._build_chat_payload(messages_list, model_config)
        return self._call_chat_api(payload, api_key)

    # NOTE[agent]: Метод извлекает полезные данные из ответа OpenAI.
    def extract_message(self, data: dict, log_entry: MessageLog) -> str:
        """Извлекает текст ответа и количество токенов из ответа API.

        Args:
            data: Ответ OpenAI API.
            log_entry: Лог-запись, которую необходимо обновить.

        Returns:
            Текст ответа модели.
        """

        if data.get("object") == "response":
            message = self._extract_text_from_response(data)
        else:
            choices = data.get("choices", [])
            if not choices:
                current_app.logger.error("Ответ OpenAI не содержит вариантов")
                raise RuntimeError("Ответ OpenAI не содержит вариантов")
            first_choice = choices[0]
            message_data = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
            message = message_data.get("content") if isinstance(message_data, dict) else None
            if not message:
                current_app.logger.error("Ответ OpenAI не содержит текста в первом варианте")
                raise RuntimeError("Ответ OpenAI не содержит текста")
            message = str(message)
        usage = data.get("usage", {})
        tokens_used = usage.get("total_tokens")
        if tokens_used is None:
            tokens_used = usage.get("completion_tokens")
        if tokens_used is None:
            tokens_used = usage.get("output_tokens")
        tokens_used = int(tokens_used or 0)
        log_entry.register_response(message, tokens_used)
        db.session.commit()
        return message

    # NOTE[agent]: Метод определяет подходящий эндпойнт OpenAI для модели.
    def _pick_endpoint_for_model(self, model_config: dict) -> str:
        """Возвращает название эндпойнта OpenAI для указанной модели."""

        endpoint = model_config.get("endpoint")
        if endpoint in {"chat", "responses"}:
            return endpoint
        model_name = str(model_config.get("model", ""))
        responses_prefixes = (
            "o1",
            "o3",
            "o4",
            "gpt-4.1",
            "gpt-4o",
            "gpt-5",
            "chatgpt-4o",
        )
        normalized = model_name.lower()
        if any(normalized.startswith(prefix) for prefix in responses_prefixes):
            return "responses"
        return "chat"

    # NOTE[agent]: Метод готовит полезную нагрузку для Chat Completions API.
    def _build_chat_payload(self, messages: list[dict[str, str]], model_config: dict) -> dict:
        """Формирует тело запроса для эндпойнта chat/completions."""

        model = model_config.get("model")
        if not model:
            raise RuntimeError("Не указана модель для запроса к OpenAI")
        payload: dict = {
            "model": model,
            "messages": messages,
        }
        for param in ("temperature", "top_p"):
            if param in model_config:
                payload[param] = model_config[param]
        return payload

    # NOTE[agent]: Метод готовит полезную нагрузку для Responses API.
    def _build_responses_payload(self, messages: list[dict[str, str]], model_config: dict) -> dict:
        """Собирает тело запроса для эндпойнта /v1/responses."""

        model = model_config.get("model")
        if not model:
            raise RuntimeError("Не указана модель для запроса к OpenAI")
        payload = {
            "model": model,
            "input": [
                {
                    "role": message.get("role", "user"),
                    "content": [
                        {
                            "type": "input_text",
                            "text": message.get("content", ""),
                        }
                    ],
                }
                for message in messages
            ],
        }
        for param in ("temperature", "top_p"):
            if param in model_config:
                payload[param] = model_config[param]
        return payload

    # NOTE[agent]: Метод отправляет запрос в Chat Completions API.
    def _call_chat_api(self, payload: dict, api_key: str) -> dict:
        """Выполняет HTTP-запрос к /v1/chat/completions."""

        return self._perform_request(self.CHAT_URL, payload, api_key, "chat")

    # NOTE[agent]: Метод отправляет запрос в Responses API.
    def _call_responses_api(self, payload: dict, api_key: str) -> dict:
        """Выполняет HTTP-запрос к /v1/responses."""

        return self._perform_request(self.RESPONSES_URL, payload, api_key, "responses")

    # NOTE[agent]: Метод выполняет HTTP-запрос и логирует обмен.
    def _perform_request(self, url: str, payload: dict, api_key: str, endpoint: str) -> dict:
        """Отправляет POST-запрос к заданному эндпойнту OpenAI."""

        current_app.logger.debug(
            "Запрос к OpenAI (%s): %s",
            endpoint,
            json.dumps({"payload": payload}, ensure_ascii=False),
        )
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            current_app.logger.exception("Ошибка при обращении к OpenAI (%s)", endpoint)
            raise RuntimeError("Не удалось выполнить запрос к OpenAI") from exc
        data = response.json()
        current_app.logger.debug(
            "Ответ OpenAI (%s): %s",
            endpoint,
            json.dumps(data, ensure_ascii=False),
        )
        return data

    # NOTE[agent]: Метод извлекает текст из ответа Responses API.
    def _extract_text_from_response(self, response: dict) -> str:
        """Извлекает текстовые блоки из ответа эндпойнта /v1/responses."""

        collected_parts: list[str] = []
        output = response.get("output", [])
        if isinstance(response.get("output_text"), str):
            collected_parts.append(str(response["output_text"]))
        for item in output:
            if not isinstance(item, dict):
                continue
            content_blocks = item.get("content", [])
            if not isinstance(content_blocks, list):
                continue
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "output_text":
                    text = block.get("text")
                    if text:
                        collected_parts.append(str(text))
                        continue
                if "text" in block and block.get("text"):
                    collected_parts.append(str(block["text"]))
                    continue
                if "value" in block and block.get("value"):
                    collected_parts.append(str(block["value"]))
        top_level_content = response.get("content", [])
        if isinstance(top_level_content, list):
            for block in top_level_content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "output_text" and block.get("text"):
                    collected_parts.append(str(block["text"]))
                    continue
                if block.get("text"):
                    collected_parts.append(str(block["text"]))
                    continue
                if block.get("value"):
                    collected_parts.append(str(block["value"]))
        if collected_parts:
            return "\n".join(part.strip() for part in collected_parts if part.strip()).strip()
        current_app.logger.error("Ответ OpenAI не содержит текста")
        raise RuntimeError("Ответ OpenAI не содержит текста")
