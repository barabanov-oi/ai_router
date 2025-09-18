"""Routes implementing the administrative web interface."""

from __future__ import annotations

from typing import Dict

from flask import Response, flash, jsonify, redirect, render_template, request, url_for

from app.models import ChatMessage
from app.services import settings_service, statistics_service, user_service
from app.web import admin_bp


# NOTE(agents): _available_modes exposes Telegram bot modes inside templates for consistency.
@admin_bp.app_context_processor
def inject_modes() -> Dict[str, str]:
    """Provide template context containing supported chat modes."""

    from app.bot.manager import AVAILABLE_MODES

    return {"available_modes": AVAILABLE_MODES}


# NOTE(agents): dashboard aggregates statistics and latest activity for administrators.
@admin_bp.route("/")
def dashboard() -> str:
    """Render overview page with high level metrics."""

    stats = statistics_service.collect_overview()
    recent = statistics_service.recent_messages(limit=10)
    openai_config = settings_service.get_openai_configuration()
    return render_template("admin/dashboard.html", stats=stats, recent=recent, openai_config=openai_config)


# NOTE(agents): list_users displays all registered Telegram users and their status.
@admin_bp.route("/users")
def list_users() -> str:
    """Render user management page with activation controls."""

    users = user_service.list_users()
    return render_template("admin/users.html", users=users)


# NOTE(agents): user_detail allows toggling activity for an individual user.
@admin_bp.route("/users/<int:user_id>", methods=["GET", "POST"])
def user_detail(user_id: int):
    """Show details about a user and allow activation toggles."""

    user = user_service.find_user(user_id)
    if user is None:
        flash("Пользователь не найден", "error")
        return redirect(url_for("admin.list_users"))
    if request.method == "POST":
        is_active = request.form.get("is_active") == "on"
        user_service.set_user_active(user, is_active)
        flash("Статус пользователя обновлён", "success")
        return redirect(url_for("admin.user_detail", user_id=user_id))
    messages = ChatMessage.query.filter_by(user_id=user_id).order_by(ChatMessage.created_at.desc()).limit(20).all()
    return render_template("admin/user_detail.html", user=user, messages=messages)


# NOTE(agents): view_logs centralises access to the request/response history for troubleshooting.
@admin_bp.route("/logs")
def view_logs() -> str:
    """Render a list of recent chat logs."""

    logs = ChatMessage.query.order_by(ChatMessage.created_at.desc()).limit(50).all()
    return render_template("admin/logs.html", logs=logs)


# NOTE(agents): settings_view lets administrators update OpenAI parameters and bot credentials.
@admin_bp.route("/settings", methods=["GET", "POST"])
def settings_view():
    """Allow administrators to update system configuration settings."""

    settings = settings_service.get_all_settings()
    if request.method == "POST":
        for key in [
            "openai_api_key",
            "openai_model",
            "openai_temperature",
            "openai_max_tokens",
            "telegram_bot_token",
        ]:
            value = request.form.get(key)
            if value is not None:
                settings_service.set_setting(key, value)
        flash("Настройки обновлены", "success")
        return redirect(url_for("admin.settings_view"))
    return render_template("admin/settings.html", settings=settings)


# NOTE(agents): settings_api exposes a programmatic way to inspect and change settings.
@admin_bp.route("/api/settings", methods=["GET", "POST"])
def settings_api() -> Response:
    """Return JSON describing settings or update them based on the HTTP method."""

    if request.method == "GET":
        return jsonify(settings_service.get_all_settings())
    payload = request.get_json(silent=True) or {}
    for key, value in payload.items():
        settings_service.set_setting(key, str(value))
    return jsonify({"status": "ok"})
