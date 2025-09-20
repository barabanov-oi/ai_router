"""Сервис выбора и использования LLM-провайдеров."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple, Type

from flask import current_app

from ..models import LLMProvider, MessageLog, ModelConfig
from .providers.base import BaseProviderClient
from .providers.google_provider import GoogleProviderClient
from .providers.groq_provider import GroqProviderClient
from .providers.openai_provider import OpenAIProviderClient


# NOTE[agent]: Сервис кеширует клиентов и делегирует им вызовы API.
class LLMService:
    """Управляет взаимодействием с поставщиками LLM."""

    _CLIENT_CLASSES: Dict[str, Type[BaseProviderClient]] = {
        LLMProvider.VENDOR_OPENAI: OpenAIProviderClient,
        LLMProvider.VENDOR_GOOGLE: GoogleProviderClient,
        LLMProvider.VENDOR_GROQ: GroqProviderClient,
    }

    def __init__(self) -> None:
        """Инициализирует кэш клиентов провайдеров."""

        self._clients: Dict[int, Tuple[str, BaseProviderClient]] = {}

    # NOTE[agent]: Метод подбирает клиента и выполняет чат-запрос.
    def complete_chat(
        self,
        *,
        model: ModelConfig,
        payload: Dict[str, Any],
        messages: Iterable[Dict[str, str]],
        log_entry: MessageLog,
    ) -> str:
        """Выполняет запрос к провайдеру и возвращает текст ответа."""

        if model.provider is None:
            raise RuntimeError("Для модели не выбран поставщик API")
        provider = model.provider
        if not provider.api_key:
            raise RuntimeError(f"API-ключ для поставщика {provider.name} не настроен")

        client = self._get_client(provider)
        current_app.logger.debug(
            "Выполняется запрос к провайдеру %s (модель %s)",
            provider.vendor,
            model.model,
        )
        data = client.send_chat_request(messages=messages, model_config=payload)
        return client.extract_message(data=data, log_entry=log_entry)

    # NOTE[agent]: Метод управляет кешем клиентов для повторного использования.
    def _get_client(self, provider: LLMProvider) -> BaseProviderClient:
        """Возвращает (и при необходимости создаёт) клиента для поставщика."""

        signature = f"{provider.vendor}:{provider.api_key}:{provider.updated_at.isoformat()}"
        cached = self._clients.get(provider.id)
        if cached and cached[0] == signature:
            return cached[1]

        client_cls = self._CLIENT_CLASSES.get(provider.vendor)
        if client_cls is None:
            raise RuntimeError(f"Поставщик {provider.vendor} пока не поддерживается")

        client = client_cls(api_key=provider.api_key)
        self._clients[provider.id] = (signature, client)
        return client
