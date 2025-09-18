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

        prepared_messages = list(messages)
        payload = {"messages": prepared_messages}
        payload.update(model_config)
        current_app.logger.debug(
            "Запрос к OpenAI (chat): %s",
            json.dumps({"payload": payload}, ensure_ascii=False),
        )

        try:
            response = self._post_openai(self.CHAT_URL, payload, api_key)
        except requests.RequestException as exc:  # pragma: no cover - сетевые сбои сложно воспроизвести
            current_app.logger.exception("Ошибка при обращении к OpenAI")
            raise RuntimeError("Не удалось выполнить запрос к OpenAI") from exc

        if response.ok:
            data = response.json()
            current_app.logger.debug("Ответ OpenAI: %s", json.dumps(data, ensure_ascii=False))
            return data

        error_payload = self._safe_json(response)
        self._log_openai_error(response, error_payload)
        if response.status_code == 400:
            try:
                data = self._call_responses_api(prepared_messages, model_config, api_key)
                current_app.logger.debug(
                    "Ответ OpenAI (responses): %s", json.dumps(data, ensure_ascii=False)
                )
                return data
            except RuntimeError:
                # NOTE[agent]: Фолбэк не помог, переиспользуем исходную ошибку.
                pass

        try:
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - повторяем причину ошибки
            raise RuntimeError("Не удалось выполнить запрос к OpenAI") from exc

        # NOTE[agent]: Сюда мы не должны попадать, но оставляем возврат на всякий случай.
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

        message = self._extract_text_from_response(data)
        if message is None:
            current_app.logger.error("Ответ OpenAI не содержит текста")
            raise RuntimeError("Ответ OpenAI не содержит вариантов")

        usage = data.get("usage", {})
        tokens_used = self._extract_tokens_used(usage)
        log_entry.register_response(message, tokens_used)
        db.session.commit()
        return message

    # NOTE[agent]: Вспомогательный метод отправляет POST-запрос в OpenAI.
    def _post_openai(self, url: str, payload: dict, api_key: str) -> requests.Response:
        """Выполняет POST-запрос к OpenAI с нужными заголовками."""

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        return requests.post(url, headers=headers, json=payload, timeout=60)

    # NOTE[agent]: Метод пытается повторить запрос через Responses API.
    def _call_responses_api(
        self,
        messages: Iterable[dict[str, str]],
        model_config: dict,
        api_key: str,
    ) -> dict:
        """Отправляет запрос в Responses API и возвращает ответ."""

        payload = self._build_responses_payload(messages, model_config)
        current_app.logger.debug(
            "Запрос к OpenAI (responses): %s",
            json.dumps({"payload": payload}, ensure_ascii=False),
        )
        try:
            response = self._post_openai(self.RESPONSES_URL, payload, api_key)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - зависит от сети/конфигурации
            error_response = response if "response" in locals() else None
            error_payload = self._safe_json(error_response)
            self._log_openai_error(error_response, error_payload)
            raise RuntimeError("Не удалось выполнить запрос к OpenAI") from exc
        return response.json()

    # NOTE[agent]: Метод формирует тело запроса для Responses API.
    def _build_responses_payload(
        self, messages: Iterable[dict[str, str]], model_config: dict
    ) -> dict:
        """Преобразует данные к формату Responses API."""

        payload: dict = {
            "input": list(messages),
        }
        for key in ("model", "temperature", "top_p", "frequency_penalty", "presence_penalty"):
            if key in model_config:
                payload[key] = model_config[key]

        if "max_tokens" in model_config and model_config["max_tokens"]:
            payload["max_output_tokens"] = model_config["max_tokens"]

        return payload

    # NOTE[agent]: Метод безопасно извлекает JSON из ответа.
    def _safe_json(self, response: requests.Response | None) -> dict:
        """Возвращает JSON-ответ, если он корректный, иначе пустой словарь."""

        if response is None:
            return {}
        try:
            return response.json()
        except ValueError:  # pragma: no cover - зависит от содержимого ответа
            return {}

    # NOTE[agent]: Метод логирует подробности об ошибке OpenAI.
    def _log_openai_error(self, response: requests.Response | None, payload: dict | None) -> None:
        """Выводит подробности ошибки OpenAI в лог."""

        if response is None:
            current_app.logger.error("Не удалось получить ответ от OpenAI")
            return
        message = payload.get("error", {}).get("message") if payload else None
        current_app.logger.error(
            "Ошибка OpenAI (%s): %s",
            response.status_code,
            message or response.text,
        )

    # NOTE[agent]: Метод извлекает текст ответа из формата Chat или Responses.
    def _extract_text_from_response(self, data: dict) -> str | None:
        """Пытается извлечь текст ответа независимо от формата API."""

        choices = data.get("choices", [])
        if choices:
            message = choices[0].get("message", {}).get("content")
            if message:
                return message

        output = data.get("output") or data.get("outputs")
        if not output:
            return None

        for item in output:
            if item.get("role") != "assistant":
                continue
            contents = item.get("content", [])
            text_parts: list[str] = []
            for content in contents:
                if isinstance(content, dict):
                    text = content.get("text") or content.get("value")
                    if text:
                        text_parts.append(str(text))
                elif isinstance(content, str):
                    text_parts.append(content)
            if text_parts:
                return "\n".join(text_parts).strip()
        return None

    # NOTE[agent]: Метод рассчитывает количество использованных токенов.
    def _extract_tokens_used(self, usage: dict) -> int:
        """Возвращает количество токенов из блока usage."""

        if not usage:
            return 0
        if "total_tokens" in usage:
            return int(usage.get("total_tokens", 0))
        completion = usage.get("completion_tokens")
        if completion is not None:
            return int(completion)
        output_tokens = usage.get("output_tokens")
        input_tokens = usage.get("input_tokens")
        if output_tokens is not None or input_tokens is not None:
            return int(output_tokens or 0) + int(input_tokens or 0)
        return 0
