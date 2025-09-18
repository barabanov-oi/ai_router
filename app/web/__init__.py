"""Веб-интерфейс администратора приложения ai_router."""

from __future__ import annotations

import logging
from typing import Any, Dict

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy.exc import SQLAlchemyError

from ..models import Conversation, ModelPreset, RequestLog, User, db
from ..services import settings_service
from ..services.conversation_service import close_conversation, get_active_conversation
from ..services.statistics_service import get_recent_logs, get_summary_stats, get_user_stats

LOGGER = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, template_folder="templates", static_folder="static")


# AGENT: Проверяет, авторизован ли администратор для доступа к панели.
@admin_bp.before_request
def ensure_admin() -> Any:
    """Гарантировать авторизованный доступ к маршрутам админ-панели."""

    open_routes = {"admin.login", "admin.static"}
    if request.endpoint in open_routes:
        return None
    if session.get("admin_authenticated"):
        return None
    return redirect(url_for("admin.login"))


# AGENT: Отображает форму входа в админ-панель.
@admin_bp.route("/login", methods=["GET", "POST"])
def login() -> Any:
    """Авторизация администратора по секретному ключу."""

    if request.method == "POST":
        provided_secret = request.form.get("secret")
        expected_secret = current_app.config.get("ADMIN_SECRET") or settings_service.get_setting(
            "admin_secret"
        )
        if provided_secret and provided_secret == expected_secret:
            session["admin_authenticated"] = True
            flash("Добро пожаловать в админ-панель!", "success")
            return redirect(url_for("admin.dashboard"))
        flash("Неверный секретный ключ", "danger")
    return render_template("admin/login.html")


# AGENT: Завершает сессию администратора.
@admin_bp.route("/logout")
def logout() -> Any:
    """Очистить сессию администратора и вернуться на страницу входа."""

    session.pop("admin_authenticated", None)
    flash("Вы вышли из админ-панели", "info")
    return redirect(url_for("admin.login"))


# AGENT: Показывает главную страницу админки со сводной статистикой.
@admin_bp.route("/")
def dashboard() -> Any:
    """Отобразить статистику системы и последние логи."""

    stats = get_summary_stats()
    logs = get_recent_logs(limit=10)
    presets = ModelPreset.query.order_by(ModelPreset.display_name.asc()).all()
    return render_template("admin/dashboard.html", stats=stats, logs=logs, presets=presets)


# AGENT: Отображает список пользователей.
@admin_bp.route("/users")
def users() -> Any:
    """Показать всех пользователей Telegram."""

    user_list = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=user_list)


# AGENT: Отображает подробную информацию о пользователе.
@admin_bp.route("/users/<int:user_id>")
def user_detail(user_id: int) -> Any:
    """Показать карточку пользователя и его активность."""

    user = User.query.get(user_id)
    if not user:
        abort(404)
    stats = get_user_stats(user_id)
    conversations = user.conversations.order_by(Conversation.created_at.desc()).all()
    logs = user.logs.order_by(RequestLog.created_at.desc()).limit(20).all()
    return render_template(
        "admin/user_detail.html",
        user=user,
        stats=stats,
        conversations=conversations,
        logs=logs,
    )


# AGENT: Управляет настройками интеграции с OpenAI и Telegram.
@admin_bp.route("/settings", methods=["GET", "POST"])
def admin_settings() -> Any:
    """Показать и обновить настройки интеграций."""

    if request.method == "POST":
        openai_key = request.form.get("openai_api_key")
        openai_model = request.form.get("openai_model")
        telegram_token = request.form.get("telegram_token")
        admin_secret = request.form.get("admin_secret")
        if openai_key:
            settings_service.set_setting("openai_api_key", openai_key)
        if openai_model:
            settings_service.set_setting("openai_model", openai_model)
        if telegram_token:
            settings_service.set_setting("telegram_bot_token", telegram_token)
        if admin_secret:
            settings_service.set_setting("admin_secret", admin_secret)
        flash("Настройки сохранены", "success")
        return redirect(url_for("admin.admin_settings"))

    context = {
        "openai_api_key": settings_service.get_setting("openai_api_key"),
        "openai_model": settings_service.get_setting("openai_model"),
        "telegram_token": settings_service.get_setting("telegram_bot_token"),
        "admin_secret": settings_service.get_setting("admin_secret"),
    }
    return render_template("admin/settings.html", **context)


# AGENT: Показывает журнал запросов.
@admin_bp.route("/logs")
def logs() -> Any:
    """Вывести детальный журнал запросов пользователей."""

    log_entries = RequestLog.query.order_by(RequestLog.created_at.desc()).limit(100).all()
    return render_template("admin/logs.html", logs=log_entries)


# AGENT: Возвращает JSON с текущими настройками.
@admin_bp.route("/api/settings", methods=["GET"])
def api_get_settings() -> Any:
    """Отдать настройки интеграций в формате JSON."""

    data = {
        "openai_model": settings_service.get_setting("openai_model"),
        "telegram_token_configured": bool(settings_service.get_setting("telegram_bot_token")),
    }
    return jsonify(data)


# AGENT: Обновляет настройки через JSON-запрос.
@admin_bp.route("/api/settings", methods=["POST"])
def api_update_settings() -> Any:
    """Обновить настройки администратора через JSON."""

    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    for key in ("openai_api_key", "openai_model", "telegram_bot_token"):
        if key in payload and payload[key]:
            settings_service.set_setting(key, payload[key])
    return jsonify({"status": "ok"})


# AGENT: Переключает доступ пользователя к боту.
@admin_bp.route("/api/users/<int:user_id>/toggle", methods=["POST"])
def api_toggle_user(user_id: int) -> Any:
    """Активировать или деактивировать пользователя."""

    user = User.query.get(user_id)
    if not user:
        abort(404)
    user.is_active = not user.is_active
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        LOGGER.exception("Не удалось переключить статус пользователя: %s", error)
        db.session.rollback()
        return jsonify({"status": "error"}), 500
    return jsonify({"status": "ok", "is_active": user.is_active})


# AGENT: Завершает активный диалог пользователя из админки.
@admin_bp.route("/api/conversations/<int:user_id>/reset", methods=["POST"])
def api_reset_conversation(user_id: int) -> Any:
    """Принудительно завершить текущий диалог пользователя."""

    user = User.query.get(user_id)
    if not user:
        abort(404)
    conversation = get_active_conversation(user)
    close_conversation(conversation)
    new_conversation = get_active_conversation(user)
    return jsonify({"status": "ok", "conversation_id": conversation.id, "new_conversation_id": new_conversation.id})
