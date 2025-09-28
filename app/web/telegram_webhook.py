"""Маршрут обработки webhook-запросов Telegram."""

from __future__ import annotations

from typing import Optional

from flask import Blueprint, Response, current_app, jsonify, request

from ..bot.bot_service import TelegramBotManager


# NOTE[agent]: Отдельный blueprint без префикса для публичного webhook.
telegram_webhook_bp = Blueprint("telegram_webhook", __name__)


# NOTE[agent]: Обработчик входящих webhook-запросов от Telegram.
@telegram_webhook_bp.route("/bot/webhook", methods=["POST"])
def telegram_webhook() -> Response:
    """Принимает webhook и передаёт обновление менеджеру бота."""

    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    payload = request.get_json(force=True)
    bot_manager.process_webhook_update(payload)
    return jsonify({"status": "received"})


__all__ = ["telegram_webhook_bp"]
