"""Маршруты административного интерфейса."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, url_for

from ...models import Dialog, MessageLog, ModelConfig, User, db
from ...services.bot_service import TelegramBotManager
from ...services.settings_service import SettingsService
from ...services.statistics_service import StatisticsService

admin_bp = Blueprint("admin", __name__, url_prefix="/admin", template_folder="../templates")


# NOTE[agent]: Точка входа в админку отображает ключевые метрики и статус бота.
@admin_bp.route("/")
def dashboard() -> str:
    """Отображает сводную статистику и основные настройки."""

    period = int(request.args.get("days", 7) or 7)
    stats = StatisticsService().gather(days=period)
    settings = SettingsService().all_settings()
    bot_manager: TelegramBotManager | None = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    is_bot_running = bot_manager.is_running() if bot_manager else False
    models = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        period=period,
        settings=settings,
        is_bot_running=is_bot_running,
        models=models,
    )


# NOTE[agent]: Страница управления пользователями позволяет изменять активность и создавать записи.
@admin_bp.route("/users", methods=["GET", "POST"])
def manage_users() -> Response | str:
    """Отображает список пользователей и обрабатывает форму добавления."""

    if request.method == "POST":
        telegram_id = request.form.get("telegram_id", "").strip()
        username = request.form.get("username", "").strip() or None
        full_name = request.form.get("full_name", "").strip() or None
        if telegram_id:
            existing = User.query.filter_by(telegram_id=telegram_id).first()
            if existing:
                existing.username = username or existing.username
                existing.full_name = full_name or existing.full_name
            else:
                user = User(telegram_id=telegram_id, username=username, full_name=full_name)
                db.session.add(user)
            db.session.commit()
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)


# NOTE[agent]: Маршрут переключает флаг активности пользователя.
@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
def toggle_user(user_id: int) -> Response:
    """Переключает доступ пользователя к боту."""

    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    return redirect(url_for("admin.manage_users"))


# NOTE[agent]: Страница с журналом сообщений для аудита.
@admin_bp.route("/logs")
def logs() -> str:
    """Показывает последние сообщения пользователей и ответы LLM."""

    limit = int(request.args.get("limit", 50) or 50)
    records = (
        MessageLog.query.order_by(MessageLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return render_template("admin/logs.html", records=records, limit=limit)


# NOTE[agent]: Управление конфигурациями моделей и выбор активной.
@admin_bp.route("/models", methods=["GET", "POST"])
def manage_models() -> Response | str:
    """Позволяет добавлять новые модели и выбирать активную."""

    settings_service = SettingsService()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        model_name = request.form.get("model", "").strip()

        # NOTE[agent]: Вспомогательная функция безопасно преобразует значение в float.
        def _float(name: str, default: float) -> float:
            """Возвращает значение поля как float или значение по умолчанию."""

            value = request.form.get(name, "")
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        # NOTE[agent]: Вспомогательная функция безопасно преобразует значение в int.
        def _int(name: str, default: int) -> int:
            """Возвращает значение поля как int или значение по умолчанию."""

            value = request.form.get(name, "")
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        temperature = _float("temperature", 1.0)
        max_tokens = _int("max_tokens", 512)
        top_p = _float("top_p", 1.0)
        frequency_penalty = _float("frequency_penalty", 0.0)
        presence_penalty = _float("presence_penalty", 0.0)
        is_default = request.form.get("is_default") == "on"
        if name and model_name:
            model = ModelConfig(
                name=name,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
                is_default=is_default,
            )
            if is_default:
                ModelConfig.query.update({ModelConfig.is_default: False})
            db.session.add(model)
            db.session.commit()
            if is_default:
                settings_service.set("active_model_id", str(model.id))
    models = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    active_model_id = settings_service.get("active_model_id")
    return render_template("admin/models.html", models=models, active_model_id=active_model_id)


# NOTE[agent]: Настройки API-ключей и параметров интеграции.
@admin_bp.route("/settings", methods=["GET", "POST"])
def manage_settings() -> Response | str:
    """Позволяет обновить интеграционные настройки системы."""

    settings_service = SettingsService()
    keys = ["openai_api_key", "telegram_bot_token", "webhook_url", "webhook_secret", "default_mode"]
    if request.method == "POST":
        for key in keys:
            settings_service.set(key, request.form.get(key, ""))
        active_model = request.form.get("active_model_id")
        if active_model:
            settings_service.set("active_model_id", active_model)
        return redirect(url_for("admin.manage_settings"))
    settings = settings_service.all_settings()
    models = ModelConfig.query.order_by(ModelConfig.name.asc()).all()
    return render_template("admin/settings.html", settings=settings, models=models)


# NOTE[agent]: API для получения всех настроек в JSON.
@admin_bp.route("/api/settings", methods=["GET", "POST"])
def api_settings() -> Response:
    """Возвращает или обновляет настройки через JSON API."""

    settings_service = SettingsService()
    if request.method == "GET":
        return jsonify(settings_service.all_settings())
    payload: dict[str, Any] = request.get_json(silent=True) or {}
    for key, value in payload.items():
        settings_service.set(key, value)
    return jsonify({"status": "ok"})


# NOTE[agent]: API-метод запуска бота в режиме polling.
@admin_bp.route("/api/bot/start-polling", methods=["POST"])
def api_start_polling() -> Response:
    """Запускает бота в режиме polling."""

    bot_manager: TelegramBotManager | None = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
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

    bot_manager: TelegramBotManager | None = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
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

    bot_manager: TelegramBotManager | None = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    bot_manager.stop()
    return jsonify({"status": "ok"})


# NOTE[agent]: Обработчик входящих webhook-запросов от Telegram.
@admin_bp.route("/bot/webhook", methods=["POST"])
def telegram_webhook() -> Response:
    """Принимает webhook и передаёт обновление менеджеру бота."""

    bot_manager: TelegramBotManager | None = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    payload = request.get_json(force=True)
    bot_manager.process_webhook_update(payload)
    return jsonify({"status": "received"})


# NOTE[agent]: Маршрут завершает диалог пользователя из админки.
@admin_bp.route("/dialogs/<int:dialog_id>/close", methods=["POST"])
def close_dialog(dialog_id: int) -> Response:
    """Помечает диалог закрытым."""

    dialog = Dialog.query.get_or_404(dialog_id)
    dialog.close()
    db.session.commit()
    return redirect(url_for("admin.logs"))
