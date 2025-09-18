"""Клиент для работы с OpenAI API."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from openai import OpenAI, OpenAIError

from ..models import ModelPreset
from .settings_service import get_openai_api_key, get_setting

LOGGER = logging.getLogger(__name__)
DEFAULT_MODEL_NAME = "gpt-3.5-turbo"


# AGENT: Создаёт клиент OpenAI с использованием актуального ключа.
def build_client() -> Optional[OpenAI]:
    """Инициализировать клиента OpenAI.

    Returns:
        Optional[OpenAI]: Экземпляр клиента или ``None``, если ключ не задан.
    """

    api_key = get_openai_api_key()
    if not api_key:
        LOGGER.error("API-ключ OpenAI не задан")
        return None
    return OpenAI(api_key=api_key)


# AGENT: Определяет имя модели на основании настроек администратора.
def resolve_model_name() -> str:
    """Получить имя модели, указанное администратором.

    Returns:
        str: Название модели или значение по умолчанию.
    """

    return get_setting("openai_model") or DEFAULT_MODEL_NAME


# AGENT: Отправляет историю сообщений в OpenAI и возвращает ответ модели.
def generate_completion(
    messages: List[Dict[str, str]],
    preset: ModelPreset,
) -> Tuple[Optional[str], Optional[Dict[str, int]], Optional[str]]:
    """Сгенерировать ответ модели на основе истории диалога.

    Args:
        messages (List[Dict[str, str]]): История сообщений в формате Chat API.
        preset (ModelPreset): Пресет с параметрами temperature и max_tokens.

    Returns:
        Tuple[Optional[str], Optional[Dict[str, int]], Optional[str]]: Ответ модели,
        статистика использования токенов и сообщение об ошибке.
    """

    client = build_client()
    if client is None:
        return None, None, "API-ключ OpenAI не настроен"

    model_name = resolve_model_name()
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=preset.temperature,
            max_tokens=preset.max_tokens,
        )
    except OpenAIError as error:
        LOGGER.exception("Ошибка обращения к OpenAI: %s", error)
        return None, None, str(error)
    except Exception as error:  # pylint: disable=broad-except
        LOGGER.exception("Непредвиденная ошибка OpenAI: %s", error)
        return None, None, str(error)

    if not response.choices:
        LOGGER.error("OpenAI вернул пустой список вариантов")
        return None, None, "Пустой ответ модели"

    message = response.choices[0].message
    content = message.content if message else None
    usage = None
    if hasattr(response, "usage") and response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    return content, usage, None
