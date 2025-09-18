"""Routes that power the administrator web interface."""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Tuple

from flask import (
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    current_app,
)
from sqlalchemy import select

from app.models import DialogMessage
from app.services import settings_service, stats_service, user_service
from app.services.database import DatabaseSessionManager
from app.web import admin_bp

LOGGER = logging.getLogger(__name__)


def _get_session_manager() -> DatabaseSessionManager:
    # Комментарий для агентов: Извлекает менеджер сессий, созданный фабрикой приложения.
    """Return database session manager stored in application context."""

    return current_app.extensions["db_session_manager"]


def _resolve_period(period: str) -> Tuple[_dt.datetime, _dt.datetime]:
    # Комментарий для агентов: Преобразует строковый период в диапазон дат.
    """Calculate start and end datetime from textual period name."""

    now = _dt.datetime.utcnow()
    if period == "day":
        start = now - _dt.timedelta(days=1)
    elif period == "week":
        start = now - _dt.timedelta(days=7)
    elif period == "month":
        start = now - _dt.timedelta(days=30)
    else:
        start = now - _dt.timedelta(days=1)
    return start, now


@admin_bp.before_request
# Комментарий для агентов: Проверяет, авторизован ли администратор перед обработкой запроса.
def require_login() -> Response | None:
    """Ensure admin is authenticated before accessing protected routes."""

    if request.endpoint in {"admin.login", "admin.static"}:
        return None
    if session.get("admin_authenticated"):
        return None
    return redirect(url_for("admin.login"))


@admin_bp.route("/login", methods=["GET", "POST"])
# Комментарий для агентов: Обрабатывает форму входа в административную панель.
def login() -> Response | str:
    """Render login form and handle credentials submission."""

    if request.method == "POST":
        password = request.form.get("password", "")
        if password == current_app.config["ADMIN_PASSWORD"]:
            session["admin_authenticated"] = True
            flash("Добро пожаловать!", "success")
            return redirect(url_for("admin.dashboard"))
        flash("Неверный пароль", "error")
    return render_template("admin/login.html")


@admin_bp.route("/logout")
# Комментарий для агентов: Завершает сессию администратора и перенаправляет на страницу входа.
def logout() -> Response:
    """Clear admin session and redirect to login page."""

    session.pop("admin_authenticated", None)
    flash("Сессия завершена", "success")
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
# Комментарий для агентов: Формирует данные для главного дашборда.
def dashboard() -> str:
    """Render dashboard with statistics and bot status."""

    period = request.args.get("period", "day")
    start, end = _resolve_period(period)
    session_manager = _get_session_manager()
    with session_manager.session_scope() as db:
        stats = stats_service.calculate_statistics(db, start, end)
        settings = settings_service.get_bot_settings(db)
        models = settings_service.list_models(db)
    bot_manager = current_app.extensions["telegram_manager"]
    status = bot_manager.get_status()
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        period=period,
        models=models,
        settings=settings,
        bot_status=status,
    )


@admin_bp.route("/users", methods=["GET", "POST"])
# Комментарий для агентов: Предоставляет список пользователей и форму ручного добавления.
def users() -> str:
    """List users and provide form for manual creation."""

    session_manager = _get_session_manager()
    if request.method == "POST":
        try:
            telegram_id = int(request.form["telegram_id"])
        except (KeyError, ValueError):
            flash("Введите корректный Telegram ID", "error")
        else:
            username = request.form.get("username") or None
            full_name = request.form.get("full_name") or None
            is_active = request.form.get("is_active") == "on"
            with session_manager.session_scope() as db:
                user = user_service.get_or_create_user(db, telegram_id, username, full_name)
                user.is_active = is_active
                flash("Пользователь сохранён", "success")
    with session_manager.session_scope() as db:
        users_list = user_service.list_users(db)
    return render_template("admin/users.html", users=users_list)


@admin_bp.post("/users/<int:user_id>/toggle")
# Комментарий для агентов: Позволяет быстро блокировать или активировать пользователя.
def toggle_user(user_id: int) -> Response:
    """Toggle availability for selected user."""

    session_manager = _get_session_manager()
    with session_manager.session_scope() as db:
        user = user_service.toggle_user_access(db, user_id)
        if user is None:
            flash("Пользователь не найден", "error")
        else:
            flash("Статус пользователя обновлён", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/models", methods=["GET", "POST"])
# Комментарий для агентов: Управляет конфигурациями моделей OpenAI.
def models() -> str:
    """List model configurations and provide creation form."""

    session_manager = _get_session_manager()
    if request.method == "POST":
        name = request.form["name"]
        api_key = request.form["api_key"]
        model_name = request.form["model_name"]
        base_url = request.form.get("base_url") or None
        temperature = float(request.form.get("temperature", 0.7))
        max_tokens = int(request.form.get("max_tokens", 1024))
        activate = request.form.get("activate") == "on"
        with session_manager.session_scope() as db:
            settings_service.create_model(
                session=db,
                name=name,
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
                temperature=temperature,
                max_tokens=max_tokens,
                activate=activate,
            )
            flash("Модель сохранена", "success")
    with session_manager.session_scope() as db:
        models_list = settings_service.list_models(db)
        settings = settings_service.get_bot_settings(db)
    return render_template("admin/models.html", models=models_list, settings=settings)


@admin_bp.post("/models/<int:model_id>/activate")
# Комментарий для агентов: Помечает конкретную модель как активную.
def activate_model(model_id: int) -> Response:
    """Mark model as active for bot requests."""

    session_manager = _get_session_manager()
    with session_manager.session_scope() as db:
        model = settings_service.set_active_model(db, model_id)
        if model is None:
            flash("Модель не найдена", "error")
        else:
            flash("Модель активирована", "success")
    return redirect(url_for("admin.models"))


@admin_bp.route("/settings", methods=["GET", "POST"])
# Комментарий для агентов: Управляет токеном бота и параметрами webhook.
def settings_view() -> str:
    """Allow administrators to update bot token and webhook data."""

    session_manager = _get_session_manager()
    if request.method == "POST":
        action = request.form.get("action")
        with session_manager.session_scope() as db:
            if action == "bot_token":
                token = request.form.get("bot_token", "")
                settings_service.update_bot_token(db, token)
                flash("Токен бота обновлён", "success")
            elif action == "webhook":
                url_value = request.form.get("webhook_url") or None
                secret = request.form.get("webhook_secret") or None
                settings_service.update_webhook_config(db, url_value, secret)
                flash("Параметры вебхука обновлены", "success")
    with session_manager.session_scope() as db:
        settings = settings_service.get_bot_settings(db)
    bot_status = current_app.extensions["telegram_manager"].get_status()
    return render_template("admin/settings.html", settings=settings, bot_status=bot_status)


@admin_bp.route("/logs")
# Комментарий для агентов: Показывает журналы обращений к LLM.
def logs() -> str:
    """Display message logs for administrator review."""

    session_manager = _get_session_manager()
    with session_manager.session_scope() as db:
        items = db.scalars(
            select(DialogMessage).order_by(DialogMessage.created_at.desc()).limit(50)
        ).all()
    return render_template("admin/logs.html", messages=items)


@admin_bp.post("/bot/start")
# Комментарий для агентов: Запускает телеграм-бота в режиме polling.
def start_bot() -> Response:
    """Trigger polling mode for Telegram bot."""

    try:
        started = current_app.extensions["telegram_manager"].start_polling()
        if started:
            flash("Бот запущен в режиме polling", "success")
        else:
            flash("Бот уже запущен", "info")
    except Exception as exc:
        LOGGER.exception("Не удалось запустить бота: %s", exc)
        flash(str(exc), "error")
    return redirect(url_for("admin.settings_view"))


@admin_bp.post("/bot/start-webhook")
# Комментарий для агентов: Переключает бота на режим webhook.
def start_bot_webhook() -> Response:
    """Configure webhook mode for Telegram bot."""

    try:
        current_app.extensions["telegram_manager"].start_webhook()
        flash("Бот переключен на webhook", "success")
    except Exception as exc:
        LOGGER.exception("Не удалось настроить webhook: %s", exc)
        flash(str(exc), "error")
    return redirect(url_for("admin.settings_view"))


@admin_bp.route("/stats")
# Комментарий для агентов: Предоставляет статистику в формате JSON для интеграций.
def stats_api() -> Response:
    """Return statistics JSON for requested period."""

    period = request.args.get("period", "day")
    start, end = _resolve_period(period)
    session_manager = _get_session_manager()
    with session_manager.session_scope() as db:
        stats = stats_service.calculate_statistics(db, start, end)
    return jsonify({"period": period, "stats": stats})


@admin_bp.app_context_processor
# Комментарий для агентов: Автоматически добавляет статус бота во все шаблоны админки.
def inject_bot_status() -> dict:
    """Expose bot status to templates as common variable."""

    status = current_app.extensions["telegram_manager"].get_status()
    return {"bot_status": status}
