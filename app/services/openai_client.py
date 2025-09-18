"""Сервис доступа к OpenAI API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable

import requests
from flask import current_app

from app.models import ModelConfig

DEFAULT_OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIService:
    """Инкапсулирует работу с API OpenAI."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

    def _build_payload(
        self,
        model_config: ModelConfig,
        messages: Iterable[Dict[str, str]],
    ) -> Dict[str, Any]:
        """Формирует тело запроса к API."""

        payload: Dict[str, Any] = {
            "model": model_config.model,
            "messages": list(messages),
            "temperature": model_config.temperature,
        }
        if model_config.max_tokens:
            payload["max_tokens"] = model_config.max_tokens
        return payload

    def send_chat_completion(
        self,
        model_config: ModelConfig,
        messages: Iterable[Dict[str, str]],
    ) -> Dict[str, Any]:
        """Отправляет запрос к OpenAI и возвращает ответ."""

        url = model_config.base_url or DEFAULT_OPENAI_URL
        headers = {
            "Authorization": f"Bearer {model_config.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(model_config, messages)
        current_app.logger.debug(
            "Отправка запроса к OpenAI: url=%s model=%s", url, model_config.model
        )
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        if response.status_code >= 400:
            self.logger.error(
                "Ошибка OpenAI API: статус %s, ответ %s", response.status_code, response.text
            )
            response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        message = choice["message"]["content"].strip()
        usage = data.get("usage", {})
        return {
            "message": message,
            "usage": usage,
            "raw": data,
        }


openai_service = OpenAIService()
"""Глобальный экземпляр сервиса для повторного использования."""
