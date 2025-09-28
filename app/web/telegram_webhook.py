"""Маршруты webhook для взаимодействия с Telegram."""

from __future__ import annotations

from typing import Optional

from flask import Blueprint, Response, current_app, jsonify, request


telegram_webhook_bp = Blueprint("telegram_webhook", __name__)

_REGISTERED_PATH: Optional[str] = None


# NOTE[agent]: Нормализуем путь webhook для регистрации маршрута.
def _normalize_webhook_path(path: str) -> str:
    """Приводит путь webhook к стандартному виду с ведущим слэшем."""

    normalized = (path or "").strip()
    if not normalized:
        return "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


# NOTE[agent]: Функция регистрирует обработчик webhook с произвольным путём.
def register_telegram_webhook_route(path: str) -> str:
    """Добавляет маршрут webhook в blueprint и возвращает использованный путь."""

    global _REGISTERED_PATH  # pylint: disable=global-statement

    normalized_path = _normalize_webhook_path(path)
    if _REGISTERED_PATH == normalized_path:
        return normalized_path

    telegram_webhook_bp.deferred_functions.clear()
    telegram_webhook_bp.add_url_rule(
        normalized_path,
        view_func=telegram_webhook_handler,
        methods=["POST"],
        endpoint="telegram_webhook.handle",
    )
    _REGISTERED_PATH = normalized_path
    return normalized_path


# NOTE[agent]: Обработчик принимает обновления от Telegram и передаёт их менеджеру бота.
def telegram_webhook_handler() -> Response:
    """Принимает JSON от Telegram и проксирует его в TelegramBotManager."""

    bot_manager = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return (
            jsonify({"status": "error", "message": "Bot manager is not configured"}),
            500,
        )
    payload = request.get_json(force=True)
    bot_manager.process_webhook_update(payload)
    return jsonify({"status": "received"})


__all__ = ["telegram_webhook_bp", "register_telegram_webhook_route"]
