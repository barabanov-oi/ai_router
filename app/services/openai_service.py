"""Инкапсуляция вызовов OpenAI API."""

from __future__ import annotations

import json
from typing import Any, Iterable

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
        """Отправляет запрос к нужному эндпойнту OpenAI в зависимости от модели.

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

        normalized_messages = list(messages)
        endpoint = self._pick_endpoint_for_model(model_config)
        if endpoint == "responses":
            return self._call_responses_api(normalized_messages, model_config, api_key)
        return self._call_chat_api(normalized_messages, model_config, api_key)

    # NOTE[agent]: Метод извлекает полезные данные из ответа OpenAI.
    def extract_message(self, data: dict, log_entry: MessageLog) -> str:
        """Извлекает текст ответа и количество токенов из ответа API.

        Args:
            data: Ответ OpenAI API.
            log_entry: Лог-запись, которую необходимо обновить.

        Returns:
            Текст ответа модели.
        """

        if "choices" in data:
            message = self._extract_text_from_chat(data)
            usage = data.get("usage") or {}
            tokens_used = int(usage.get("total_tokens", usage.get("completion_tokens", 0)))
        else:
            message = self._extract_text_from_response(data)
            usage_source: dict[str, Any]
            usage_data = data.get("usage")
            if isinstance(usage_data, dict):
                usage_source = usage_data
            else:
                response_block = data.get("response")
                if isinstance(response_block, dict) and isinstance(response_block.get("usage"), dict):
                    usage_source = response_block.get("usage", {})
                else:
                    usage_source = {}
            tokens_used = int(
                usage_source.get(
                    "total_tokens",
                    usage_source.get("output_tokens", usage_source.get("input_tokens", 0)),
                )
            )
        log_entry.register_response(message, tokens_used)
        db.session.commit()
        return message

    def _pick_endpoint_for_model(self, model_config: dict) -> str:
        """Определяет подходящий эндпойнт OpenAI для модели."""

        preferred = model_config.get("endpoint") or model_config.get("api") or model_config.get("api_type")
        if preferred in {"chat", "responses"}:
            return preferred
        model_name = str(model_config.get("model", ""))
        responses_prefixes = ("gpt-4.1", "gpt-4o", "o4", "o3", "o1")
        if any(model_name.startswith(prefix) for prefix in responses_prefixes):
            return "responses"
        return "chat"

    def _call_chat_api(self, messages: list[dict[str, Any]], model_config: dict, api_key: str) -> dict:
        """Выполняет запрос к эндпойнту chat/completions."""

        payload = self._build_chat_payload(messages, model_config)
        current_app.logger.debug("Запрос к OpenAI (chat): %s", json.dumps({"payload": payload}, ensure_ascii=False))
        return self._perform_request(self.CHAT_URL, payload, api_key)

    def _call_responses_api(self, messages: list[dict[str, Any]], model_config: dict, api_key: str) -> dict:
        """Выполняет запрос к эндпойнту responses."""

        payload = self._build_responses_payload(messages, model_config)
        current_app.logger.debug(
            "Запрос к OpenAI (responses): %s", json.dumps({"payload": payload}, ensure_ascii=False)
        )
        return self._perform_request(self.RESPONSES_URL, payload, api_key)

    def _build_chat_payload(self, messages: list[dict[str, Any]], model_config: dict) -> dict:
        """Формирует полезную нагрузку для Chat Completions."""

        payload: dict[str, Any] = {
            "model": model_config.get("model"),
            "messages": messages,
        }
        if "temperature" in model_config:
            payload["temperature"] = model_config["temperature"]
        if "top_p" in model_config:
            payload["top_p"] = model_config["top_p"]
        return payload

    def _build_responses_payload(self, messages: list[dict[str, Any]], model_config: dict) -> dict:
        """Собирает нагрузку для эндпойнта Responses."""

        payload: dict[str, Any] = {
            "model": model_config.get("model"),
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
        if "temperature" in model_config:
            payload["temperature"] = model_config["temperature"]
        if "top_p" in model_config:
            payload["top_p"] = model_config["top_p"]
        return payload

    def _perform_request(self, url: str, payload: dict, api_key: str) -> dict:
        """Отправляет POST-запрос к OpenAI и возвращает распарсенный ответ."""

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
        data = response.json()
        current_app.logger.debug("Ответ OpenAI: %s", json.dumps(data, ensure_ascii=False))
        return data

    def _extract_text_from_chat(self, data: dict) -> str:
        """Достаёт текст ответа из структуры chat/completions."""

        choices = data.get("choices", [])
        if not choices:
            current_app.logger.error("Ответ OpenAI не содержит вариантов")
            raise RuntimeError("Ответ OpenAI не содержит вариантов")
        message = choices[0].get("message", {}).get("content")
        if message is None:
            current_app.logger.error("Ответ OpenAI не содержит текста")
            raise RuntimeError("Ответ OpenAI не содержит текста")
        return str(message)

    def _extract_text_from_response(self, data: dict) -> str:
        """Извлекает текст ответа из структуры Responses API."""

        outputs: list[dict[str, Any]] = []
        if isinstance(data.get("output"), list):
            outputs = data.get("output", [])
        elif isinstance(data.get("response"), dict) and isinstance(data["response"].get("output"), list):
            outputs = data["response"].get("output", [])
        elif isinstance(data.get("response"), list):
            outputs = data.get("response", [])

        collected: list[str] = []
        for item in outputs:
            contents = item.get("content") if isinstance(item, dict) else None
            if not isinstance(contents, list):
                continue
            for part in contents:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "output_text":
                    text_piece = part.get("text")
                    if isinstance(text_piece, str):
                        collected.append(text_piece)
                    continue
                if isinstance(part.get("text"), str):
                    collected.append(part["text"])
                    continue
                if isinstance(part.get("text"), dict):
                    value = part["text"].get("value")
                    if isinstance(value, str):
                        collected.append(value)
                    continue
                if isinstance(part.get("value"), str):
                    collected.append(part["value"])

        if collected:
            return "\n".join(piece for piece in collected if piece).strip()

        current_app.logger.error("Ответ OpenAI не содержит текстовых данных")
        raise RuntimeError("Ответ OpenAI не содержит текстовых данных")
