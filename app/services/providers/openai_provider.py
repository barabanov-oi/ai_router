"""Клиент взаимодействия с OpenAI Chat Completion API."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from flask import current_app
from openai import OpenAI

from ...models import MessageLog, db
from .base import BaseProviderClient


# NOTE[agent]: Клиент реализует протокол общения с OpenAI.
class OpenAIProviderClient(BaseProviderClient):
    """Реализует логику отправки сообщений в OpenAI."""

    _MODEL_PARAM_RULES: Optional[Dict[str, Dict[str, Any]]] = None

    # NOTE[agent]: Метод подготавливает сообщения и выполняет HTTP-запрос.
    def send_chat_request(
        self,
        *,
        messages: Iterable[Dict[str, str]],
        model_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Отправляет запрос в OpenAI Chat Completion API."""

        sanitized_config = self._sanitize_model_config(model_config)
        payload = {"messages": list(messages), **sanitized_config}
        current_app.logger.debug(
            "Запрос к OpenAI: %s",
            json.dumps({"payload": payload}, ensure_ascii=False),
        )

        try:
            client = OpenAI(api_key=self._api_key)
            response = client.chat.completions.create(**payload)
        except Exception as exc:  # pylint: disable=broad-except
            current_app.logger.exception("Ошибка при обращении к OpenAI")
            raise RuntimeError("Не удалось выполнить запрос к OpenAI") from exc

        data = response.model_dump()
        current_app.logger.debug("Ответ OpenAI: %s", json.dumps(data, ensure_ascii=False))
        return data

    # NOTE[agent]: Метод извлекает полезные данные из ответа OpenAI.
    def extract_message(self, *, data: Dict[str, Any], log_entry: MessageLog) -> str:
        """Извлекает текст ответа и количество токенов."""

        choices = data.get("choices", [])
        if not choices:
            current_app.logger.error("Ответ OpenAI не содержит вариантов")
            raise RuntimeError("Ответ OpenAI не содержит вариантов")
        message = self._strip_think_tags(choices[0]["message"].get("content"))
        usage = data.get("usage", {})
        tokens_used = int(usage.get("total_tokens", usage.get("completion_tokens", 0)))
        log_entry.register_response(message, tokens_used)
        db.session.commit()
        return message

    @staticmethod
    def _strip_think_tags(text: Optional[str]) -> str:
        """Удаляет из ответа блоки вида <think>...</think>."""

        return re.sub(r"(?is)<think>.*?</think>", "", text or "").strip()

    @classmethod
    def _get_param_rules(cls) -> Dict[str, Dict[str, Any]]:
        """Возвращает правила доступных параметров для моделей OpenAI."""

        if cls._MODEL_PARAM_RULES is None:
            config_path = Path(__file__).with_name("openai_model_params.json")
            try:
                with config_path.open("r", encoding="utf-8") as fp:
                    cls._MODEL_PARAM_RULES = json.load(fp)
            except FileNotFoundError as exc:  # pragma: no cover - защита от некорректной конфигурации
                raise RuntimeError("Не найден файл конфигурации параметров моделей OpenAI") from exc
        return cls._MODEL_PARAM_RULES

    # NOTE[agent]: Метод приводит конфигурацию к допустимому набору параметров.
    def _sanitize_model_config(self, model_config: Dict[str, Any]) -> Dict[str, Any]:
        """Приводит конфигурацию модели к параметрам, поддерживаемым API."""

        model_name = model_config.get("model")
        if not model_name:
            raise RuntimeError("Конфигурация модели не содержит ключ 'model'")

        rules = self._resolve_rules_for_model(model_name)
        allowed = set(rules.get("allowed_params", [])) or {"model"}
        allowed.add("model")
        aliases = rules.get("aliases", {})
        sanitized: Dict[str, Any] = {}
        dropped: Dict[str, str] = {}

        for key, value in model_config.items():
            target_key = aliases.get(key, key)
            if target_key not in allowed:
                dropped[key] = target_key
                continue
            if target_key in sanitized and target_key != key:
                continue
            sanitized[target_key] = value

        if dropped:
            current_app.logger.debug(
                "Следующие параметры были исключены для модели %s: %s",
                model_name,
                dropped,
            )
        return sanitized

    # NOTE[agent]: Метод выбирает подходящее правило для указанной модели.
    def _resolve_rules_for_model(self, model_name: str) -> Dict[str, Any]:
        """Подбирает правила параметров для указанной модели."""

        rules_map = self._get_param_rules()
        if model_name in rules_map:
            return rules_map[model_name]

        matched_rule: Optional[Dict[str, Any]] = None
        matched_prefix_length = -1
        for key, rules in rules_map.items():
            if key == "default":
                continue
            if model_name.startswith(key) and len(key) > matched_prefix_length:
                matched_rule = rules
                matched_prefix_length = len(key)

        if matched_rule is not None:
            return matched_rule
        return rules_map.get("default", {})
