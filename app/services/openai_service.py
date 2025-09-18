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
    """Обеспечивает отправку сообщений к OpenAI и обработку ответа."""

    CHAT_URL = "https://api.openai.com/v1/chat/completions"
    RESPONSES_URL = "https://api.openai.com/v1/responses"
    RESPONSES_MODEL_PREFIXES = ("gpt-4.1", "o1", "o3")

    def __init__(self) -> None:
        """Инициализирует сервис и проверяет наличие API-ключа."""

        self._settings = SettingsService()

    # NOTE[agent]: Метод подготавливает сообщения и выполняет HTTP-запрос.
    def send_chat_request(self, messages: Iterable[dict[str, str]], model_config: dict) -> dict:
        """Отправляет запрос в OpenAI и возвращает ответ в виде словаря.

        Метод автоматически определяет, какой REST-эндпоинт OpenAI использовать.
        Для моделей, требующих Responses API, запрос отправляется на `/v1/responses`.
        В остальных случаях используется совместимый Chat Completions API.

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

        prepared_messages = list(messages)
        use_responses_api = self._should_use_responses_api(model_config)

        try:
            if use_responses_api:
                response = self._perform_responses_request(api_key, prepared_messages, model_config)
            else:
                response = self._perform_chat_request(api_key, prepared_messages, model_config)
        except requests.HTTPError as exc:
            if not use_responses_api and self._should_retry_with_responses(exc.response, model_config):
                current_app.logger.warning(
                    "Модель %s требует Responses API, повторяем запрос", model_config.get("model")
                )
                try:
                    response = self._perform_responses_request(api_key, prepared_messages, model_config)
                except requests.RequestException as retry_exc:  # pragma: no cover - повторная ошибка логируется ниже
                    current_app.logger.exception("Ошибка при обращении к OpenAI")
                    raise RuntimeError("Не удалось выполнить запрос к OpenAI") from retry_exc
            else:
                current_app.logger.exception("Ошибка при обращении к OpenAI")
                raise RuntimeError("Не удалось выполнить запрос к OpenAI") from exc
        except requests.RequestException as exc:
            current_app.logger.exception("Ошибка при обращении к OpenAI")
            raise RuntimeError("Не удалось выполнить запрос к OpenAI") from exc

        data = response.json()
        current_app.logger.debug("Ответ OpenAI: %s", json.dumps(data, ensure_ascii=False))
        return data

    # NOTE[agent]: Метод отправляет запрос в устаревший Chat Completions API.
    def _perform_chat_request(
        self,
        api_key: str,
        messages: list[dict[str, str]],
        model_config: dict,
    ) -> requests.Response:
        """Отправляет запрос в Chat Completions API и возвращает HTTP-ответ."""

        payload = self._build_chat_payload(messages, model_config)
        current_app.logger.debug("Запрос к OpenAI (chat): %s", json.dumps({"payload": payload}, ensure_ascii=False))
        response = requests.post(
            self.CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        return response

    # NOTE[agent]: Метод обращается к современному Responses API.
    def _perform_responses_request(
        self,
        api_key: str,
        messages: list[dict[str, str]],
        model_config: dict,
    ) -> requests.Response:
        """Отправляет запрос в Responses API и возвращает HTTP-ответ."""

        payload = self._build_responses_payload(messages, model_config)
        current_app.logger.debug("Запрос к OpenAI (responses): %s", json.dumps({"payload": payload}, ensure_ascii=False))
        response = requests.post(
            self.RESPONSES_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        return response

    # NOTE[agent]: Метод собирает полезную нагрузку для Chat Completions API.
    def _build_chat_payload(self, messages: list[dict[str, str]], model_config: dict) -> dict:
        """Формирует полезную нагрузку для Chat Completions API."""

        payload = {"messages": messages}
        payload.update(model_config)
        if "model" not in payload:
            payload["model"] = "gpt-4o-mini"
        return payload

    # NOTE[agent]: Метод готовит данные запроса для Responses API.
    def _build_responses_payload(self, messages: list[dict[str, str]], model_config: dict) -> dict:
        """Формирует полезную нагрузку для Responses API."""

        payload = {"input": messages}
        for key, value in model_config.items():
            if key == "max_tokens":
                payload["max_output_tokens"] = value
            elif key not in {"messages"}:
                payload[key] = value
        if "model" not in payload:
            payload["model"] = "gpt-4o-mini"
        return payload

    # NOTE[agent]: Метод определяет необходимость использования Responses API.
    def _should_use_responses_api(self, model_config: dict) -> bool:
        """Определяет, требуется ли для модели использование Responses API."""

        model_name = str(model_config.get("model", "")).lower()
        return any(model_name.startswith(prefix) for prefix in self.RESPONSES_MODEL_PREFIXES)

    # NOTE[agent]: Метод решает, стоит ли повторять запрос через Responses API.
    def _should_retry_with_responses(self, response: requests.Response | None, model_config: dict) -> bool:
        """Решает, стоит ли повторить запрос через Responses API после ошибки."""

        if response is None or response.status_code != 400:
            return False
        try:
            error_payload = response.json()
        except ValueError:  # pragma: no cover - OpenAI всегда возвращает JSON, но защищаемся от неожиданностей
            return False
        message = str(error_payload.get("error", {}).get("message", "")).lower()
        hints = (
            "use the responses endpoint",
            "use the responses api",
            "responses endpoint",
        )
        if any(hint in message for hint in hints):
            return True
        return self._should_use_responses_api(model_config)

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
            choices = data.get("choices", [])
            if not choices:
                current_app.logger.error("Ответ OpenAI не содержит вариантов")
                raise RuntimeError("Ответ OpenAI не содержит вариантов")
            message = choices[0]["message"]["content"]
        else:
            outputs = data.get("output", [])
            message = self._extract_text_from_responses(outputs)
            if not message:
                current_app.logger.error("Ответ OpenAI не содержит текстового сообщения")
                raise RuntimeError("Ответ OpenAI не содержит текстового сообщения")
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
        output_tokens = usage.get(
            "completion_tokens",
            usage.get("output_tokens", 0),
        )
        tokens_used = int(usage.get("total_tokens", input_tokens + output_tokens))
        log_entry.register_response(message, tokens_used)
        db.session.commit()
        return message

    # NOTE[agent]: Метод извлекает текст из ответа Responses API.
    def _extract_text_from_responses(self, outputs: list[dict]) -> str:
        """Извлекает текст из ответа Responses API."""

        for item in outputs:
            contents = item.get("content", [])
            for content in contents:
                text = content.get("text") or content.get("output_text")
                if text:
                    return text
        return ""
