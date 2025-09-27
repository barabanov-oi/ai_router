"""JSON API и служебные маршруты управления ботом."""

from __future__ import annotations

from typing import Any, Dict, Optional

from flask import Response, current_app, jsonify, request

from ...bot.bot_service import PollingStopTimeoutError, TelegramBotManager
from ...services.settings_service import SettingsService
from . import admin_bp


# NOTE[agent]: API для получения всех настроек в JSON.
@admin_bp.route("/api/settings", methods=["GET", "POST"])
def api_settings() -> Response:
    """Возвращает или обновляет настройки через JSON API."""

    settings_service = SettingsService()
    if request.method == "GET":
        return jsonify(settings_service.all_settings())
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    for key, value in payload.items():
        settings_service.set(key, value)
    return jsonify({"status": "ok"})


# NOTE[agent]: API-метод запуска бота в режиме polling.
@admin_bp.route("/api/bot/start-polling", methods=["POST"])
def api_start_polling() -> Response:
    """Запускает бота в режиме polling."""

    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    try:
        bot_manager.start_polling()
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.exception("Не удалось запустить polling")
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({"status": "ok"})


# NOTE[agent]: API-метод запуска webhook.
@admin_bp.route("/api/bot/start-webhook", methods=["POST"])
def api_start_webhook() -> Response:
    """Устанавливает webhook для Telegram."""

    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    try:
        url = bot_manager.start_webhook()
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.exception("Не удалось установить webhook")
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({"status": "ok", "webhook_url": url})


# NOTE[agent]: API-метод остановки бота.
@admin_bp.route("/api/bot/stop", methods=["POST"])
def api_stop_bot() -> Response:
    """Останавливает polling Telegram-бота."""

    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    try:
        bot_manager.stop()
    except PollingStopTimeoutError as exc:
        current_app.logger.exception("Не удалось остановить polling вовремя")
        return (
            jsonify({
                "status": "error",
                "message": str(exc),
            }),
            503,
        )
    return jsonify({"status": "ok"})


# NOTE[agent]: API-метод переключает режим приостановки бота.
@admin_bp.route("/api/bot/toggle-pause", methods=["POST"])
def api_toggle_bot_pause() -> Response:
    """Активирует или отключает режим приостановки Telegram-бота."""

    settings_service = SettingsService()
    current_value = (settings_service.get("bot_paused", "0") or "").strip().lower()
    is_paused = current_value in {"1", "true", "yes", "on"}
    new_value = "0" if is_paused else "1"
    settings_service.set("bot_paused", new_value)
    return jsonify({"status": "ok", "paused": new_value == "1"})


# NOTE[agent]: Обработчик входящих webhook-запросов от Telegram.
@admin_bp.route("/bot/webhook", methods=["POST"])
def telegram_webhook() -> Response:
    """Принимает webhook и передаёт обновление менеджеру бота."""

    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    payload = request.get_json(force=True)
    bot_manager.process_webhook_update(payload)
    return jsonify({"status": "received"})
