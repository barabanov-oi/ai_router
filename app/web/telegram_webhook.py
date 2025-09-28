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


_CURRENT_WEBHOOK_RULE: Optional[str] = None


def configure_webhook_route(rule: str) -> None:
    """Привязывает обработчик webhook к переданному пути."""

    global _CURRENT_WEBHOOK_RULE  # pylint: disable=global-statement

    requested_rule = (rule or "").strip()
    normalized_rule = "/bot/webhook"
    if requested_rule:
        normalized_rule = requested_rule if requested_rule.startswith("/") else f"/{requested_rule}"
    if _CURRENT_WEBHOOK_RULE == normalized_rule:
        return

    if _CURRENT_WEBHOOK_RULE is not None and telegram_webhook_bp.deferred_functions:
        telegram_webhook_bp.deferred_functions.clear()
    telegram_webhook_bp.add_url_rule(
        normalized_rule,
        view_func=telegram_webhook,
        methods=["POST"],
    )
    _CURRENT_WEBHOOK_RULE = normalized_rule


__all__ = ["telegram_webhook_bp", "configure_webhook_route", "telegram_webhook"]
