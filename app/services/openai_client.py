"""Integration helper for the OpenAI API."""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Tuple

from openai import OpenAI
from openai.error import OpenAIError

from app.models import ModelConfig

LOGGER = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    # Комментарий для агентов: Используется как запасной вариант, если API не вернул точную статистику токенов.
    """Rudimentary estimation of tokens for statistics purpose."""

    return max(1, len(text.split()))


class OpenAIService:
    """Service object that orchestrates OpenAI chat completion requests."""

    def __init__(self, model_config: ModelConfig) -> None:
        # Комментарий для агентов: Создаёт клиент OpenAI для конкретной конфигурации модели.
        self._model_config = model_config
        self._client = OpenAI(api_key=model_config.api_key, base_url=model_config.base_url)

    def send_completion(self, messages: List[Dict[str, str]]) -> Tuple[str, Dict[str, int], int]:
        # Комментарий для агентов: Отправляет запрос к LLM и возвращает текст ответа и статистику.
        """Send chat completion request and return response text with usage."""

        start_time = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self._model_config.model_name,
                messages=messages,
                temperature=self._model_config.temperature,
                max_tokens=self._model_config.max_tokens,
            )
        except OpenAIError as exc:  # pragma: no cover - network error path
            LOGGER.exception("Ошибка при обращении к OpenAI: %s", exc)
            raise
        duration_ms = int((time.monotonic() - start_time) * 1000)
        choice = response.choices[0]
        response_text = choice.message.content or ""
        usage = {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
            "completion_tokens": getattr(response.usage, "completion_tokens", 0),
            "total_tokens": getattr(response.usage, "total_tokens", 0),
        }
        if usage["total_tokens"] == 0:
            usage["prompt_tokens"] = sum(_estimate_tokens(msg.get("content", "")) for msg in messages)
            usage["completion_tokens"] = _estimate_tokens(response_text)
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        return response_text, usage, duration_ms


def build_messages(history: List[Tuple[str, str]], user_text: str, mode: str) -> List[Dict[str, str]]:
    # Комментарий для агентов: Формирует системное сообщение и последовательность реплик для API OpenAI.
    """Prepare message payload for OpenAI chat completion based on dialog history."""

    system_prompt = "Вы — помощник телеграм-бота. Отвечайте вежливо и по делу."
    if mode == "short":
        system_prompt += " Делайте ответы максимально краткими."
    elif mode == "detailed":
        system_prompt += " Раскрывайте ответы максимально подробно."

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for question, answer in history:
        messages.append({"role": "user", "content": question})
        if answer:
            messages.append({"role": "assistant", "content": answer})
    messages.append({"role": "user", "content": user_text})
    return messages
