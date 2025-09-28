"""Маршрут обработки webhook-запросов Telegram."""

from __future__ import annotations

from typing import Optional

from flask import Blueprint, Response, current_app, jsonify, request

from ..bot.bot_service import TelegramBotManager


# NOTE[agent]: Отдельный blueprint без префикса для публичного webhook.
telegram_webhook_bp = Blueprint("telegram_webhook", __name__)


# NOTE[agent]: Обработчик входящих webhook-запросов от Telegram.
def telegram_webhook() -> Response:
    """Принимает webhook и передаёт обновление менеджеру бота."""

    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    payload = request.get_json(force=True)
    bot_manager.process_webhook_update(payload)
    return jsonify({"status": "received"})


def register_telegram_webhook_route(path: str) -> str:
    """Привязывает обработчик webhook к переданному пути."""

    normalized_path = "/" + path.lstrip("/") if path else "/bot/webhook"
    # NOTE[agent]: Очищаем ранее записанные обработчики, чтобы обновить путь без дублирования правил.
    telegram_webhook_bp.deferred_functions.clear()  # type: ignore[attr-defined]
    telegram_webhook_bp.view_functions.pop("telegram_webhook", None)
    telegram_webhook_bp.add_url_rule(
        normalized_path,
        endpoint="telegram_webhook",
        view_func=telegram_webhook,
        methods=["POST"],
    )
    return normalized_path


__all__ = ["telegram_webhook_bp", "register_telegram_webhook_route", "telegram_webhook"]
