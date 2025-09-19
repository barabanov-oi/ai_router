"""Маршруты административного интерфейса."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Mapping

from flask import Blueprint, Response, abort, current_app, jsonify, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload, subqueryload

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
    start_date_str = request.args.get("start_date", "")
    end_date_str = request.args.get("end_date", "")
    start_date = _parse_date(start_date_str, end_of_day=False)
    end_date = _parse_date(end_date_str, end_of_day=True)
    stats = StatisticsService().gather(days=period, start=start_date, end=end_date)
    settings = SettingsService().all_settings()
    bot_manager: TelegramBotManager | None = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    is_bot_running = bot_manager.is_running() if bot_manager else False
    models = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    active_model = _resolve_active_model(models, settings.get("active_model_id"))
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        period=period,
        period_days=period,
        start_date=start_date_str,
        end_date=end_date_str,
        settings=settings,
        is_bot_running=is_bot_running,
        models=models,
        active_model=active_model,
    )


# NOTE[agent]: Страница управления пользователями отображает текущее состояние аккаунтов.
@admin_bp.route("/users")
def manage_users() -> str:
    """Отображает список пользователей."""

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
    dialog_limit = int(request.args.get("dialog_limit", 20) or 20)
    records = (
        MessageLog.query.order_by(MessageLog.created_at.desc())
        .limit(limit)
        .all()
    )
    dialogs = (
        Dialog.query.options(joinedload(Dialog.user), subqueryload(Dialog.messages))
        .order_by(Dialog.started_at.desc())
        .limit(dialog_limit)
        .all()
    )
    dialog_logs = [_summarize_dialog(dialog) for dialog in dialogs]
    return render_template(
        "admin/logs.html",
        records=records,
        limit=limit,
        dialog_limit=dialog_limit,
        dialog_logs=dialog_logs,
    )


# NOTE[agent]: Управление конфигурациями моделей и выбор активной.
@admin_bp.route("/models", methods=["GET", "POST"])
def manage_models() -> Response | str:
    """Позволяет добавлять новые модели и выбирать активную."""

    settings_service = SettingsService()
    if request.method == "POST":
        action = request.form.get("action", "create")
        if action == "update":
            _update_model(request.form, settings_service)
        else:
            _create_model(request.form, settings_service)
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


def _parse_date(value: str | None, *, end_of_day: bool) -> datetime | None:
    """Преобразует значение из формы в объект datetime."""

    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    moment = time.max if end_of_day else time.min
    return datetime.combine(parsed.date(), moment)


def _resolve_active_model(models: list[ModelConfig], stored_id: str | None) -> ModelConfig | None:
    """Определяет активную модель исходя из настроек и флагов."""

    target_id: int | None = None
    if stored_id:
        try:
            target_id = int(stored_id)
        except (TypeError, ValueError):
            target_id = None
    if target_id is not None:
        for model in models:
            if model.id == target_id:
                return model
    for model in models:
        if model.is_default:
            return model
    return models[0] if models else None


def _summarize_dialog(dialog: Dialog) -> dict[str, Any]:
    """Готовит словарь с агрегированной информацией о диалоге."""

    messages = sorted(dialog.messages, key=lambda message: message.message_index)
    first_message = messages[0].user_message if messages else ""
    title = first_message[:15] if first_message else "—"
    tokens_spent = sum(message.tokens_used or 0 for message in messages)
    user = dialog.user
    username = (user.username or user.telegram_id) if user else "—"
    return {
        "id": dialog.id,
        "title": title,
        "message_count": len(messages),
        "username": username,
        "tokens_spent": tokens_spent,
    }


def _get_form_float(form: Mapping[str, str | None], field: str, default: float) -> float:
    """Извлекает вещественное значение из формы."""

    value = form.get(field)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_form_int(form: Mapping[str, str | None], field: str, default: int) -> int:
    """Извлекает целочисленное значение из формы."""

    value = form.get(field)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _create_model(form: Mapping[str, str | None], settings_service: SettingsService) -> None:
    """Создаёт новую конфигурацию модели на основе формы."""

    name = (form.get("name") or "").strip()
    model_name = (form.get("model") or "").strip()
    if not name or not model_name:
        return
    temperature = _get_form_float(form, "temperature", 1.0)
    max_tokens = _get_form_int(form, "max_tokens", 512)
    top_p = _get_form_float(form, "top_p", 1.0)
    instruction = (form.get("instruction") or "").strip() or None
    is_default = form.get("is_default") == "on"
    if is_default:
        ModelConfig.query.update({ModelConfig.is_default: False})
    model = ModelConfig(
        name=name,
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        instruction=instruction,
        is_default=is_default,
    )
    db.session.add(model)
    db.session.commit()
    if is_default:
        settings_service.set("active_model_id", str(model.id))


def _update_model(form: Mapping[str, str | None], settings_service: SettingsService) -> None:
    """Обновляет существующую конфигурацию модели."""

    raw_id = form.get("model_id")
    if not raw_id:
        abort(400, "Не указан идентификатор модели")
    try:
        model_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise abort(400, "Некорректный идентификатор модели") from exc
    model = ModelConfig.query.get(model_id)
    if not model:
        abort(404, "Модель не найдена")
    name = (form.get("name") or "").strip()
    model_name = (form.get("model") or "").strip()
    if name:
        model.name = name
    if model_name:
        model.model = model_name
    model.temperature = _get_form_float(form, "temperature", model.temperature)
    model.max_tokens = _get_form_int(form, "max_tokens", model.max_tokens)
    model.top_p = _get_form_float(form, "top_p", model.top_p)
    instruction = (form.get("instruction") or "").strip()
    model.instruction = instruction or None
    is_default = form.get("is_default") == "on"
    if is_default:
        ModelConfig.query.update({ModelConfig.is_default: False})
    model.is_default = is_default
    db.session.commit()
    if is_default:
        settings_service.set("active_model_id", str(model.id))
