"""Административный веб-интерфейс."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Dict

from flask import Blueprint, Response, current_app, jsonify, render_template, request

from app.models import ModelConfig, User, db
from app.services import bot_runner, conversations, settings as settings_service, statistics

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="templates",
    static_folder="static",
)
"""Blueprint административного интерфейса."""


@admin_bp.route("/")
def dashboard() -> str:
    """Отображает главную страницу админки."""

    return render_template("admin/dashboard.html")


@admin_bp.route("/api/users", methods=["GET", "POST"])
def manage_users() -> Response:
    """Возвращает список пользователей или создаёт нового."""

    if request.method == "POST":
        payload: Dict[str, Any] = request.get_json(force=True)
        telegram_id = payload.get("telegram_id")
        username = payload.get("username")
        if telegram_id is None:
            return jsonify({"error": "telegram_id обязателен"}), HTTPStatus.BAD_REQUEST
        try:
            telegram_id_int = int(telegram_id)
        except (TypeError, ValueError):
            return jsonify({"error": "Неверный формат telegram_id"}), HTTPStatus.BAD_REQUEST
        user = conversations.get_or_create_user(telegram_id_int, username)
        user.is_active = payload.get("is_active", True)
        user.is_admin = payload.get("is_admin", False)
        user.subscription_type = payload.get("subscription_type", user.subscription_type)
        db.session.commit()
        return jsonify(user.to_dict()), HTTPStatus.CREATED

    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([user.to_dict() for user in users])


@admin_bp.route("/api/users/<int:user_id>", methods=["PATCH"])
def update_user(user_id: int) -> Response:
    """Обновляет данные пользователя."""

    user = User.query.get_or_404(user_id)
    payload = request.get_json(force=True)
    if "is_active" in payload:
        user.is_active = bool(payload["is_active"])
    if "subscription_type" in payload:
        user.subscription_type = payload["subscription_type"]
    if "is_admin" in payload:
        user.is_admin = bool(payload["is_admin"])
    db.session.commit()
    return jsonify(user.to_dict())


@admin_bp.route("/api/models", methods=["GET", "POST"])
def manage_models() -> Response:
    """Возвращает список моделей или создаёт новую конфигурацию."""

    if request.method == "POST":
        payload = request.get_json(force=True)
        required = {"name", "display_name", "api_key", "model"}
        if not required.issubset(payload):
            return (
                jsonify({"error": "Отсутствуют обязательные поля", "required": sorted(required)}),
                HTTPStatus.BAD_REQUEST,
            )
        model_config = ModelConfig(
            name=payload["name"],
            display_name=payload["display_name"],
            api_key=payload["api_key"],
            base_url=payload.get("base_url"),
            model=payload["model"],
            temperature=payload.get("temperature", 0.7),
            max_tokens=payload.get("max_tokens"),
            is_default=payload.get("is_default", False),
            is_active=payload.get("is_active", True),
        )
        if model_config.is_default:
            ModelConfig.query.update({ModelConfig.is_default: False})
        db.session.add(model_config)
        db.session.commit()
        return jsonify(model_config.to_dict()), HTTPStatus.CREATED

    models = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    return jsonify([model.to_dict() for model in models])


@admin_bp.route("/api/models/<int:model_id>", methods=["PATCH"])
def update_model(model_id: int) -> Response:
    """Обновляет конфигурацию модели."""

    model = ModelConfig.query.get_or_404(model_id)
    payload = request.get_json(force=True)
    for field in ["display_name", "api_key", "base_url", "model", "temperature", "max_tokens"]:
        if field in payload:
            setattr(model, field, payload[field])
    if "is_active" in payload:
        model.is_active = bool(payload["is_active"])
    if payload.get("is_default"):
        ModelConfig.query.update({ModelConfig.is_default: False})
        model.is_default = True
    db.session.commit()
    return jsonify(model.to_dict())


@admin_bp.route("/api/settings", methods=["GET"])
def get_settings() -> Response:
    """Возвращает все настройки приложения."""

    return jsonify(settings_service.get_all_settings())


@admin_bp.route("/api/settings/<string:key>", methods=["PUT"])
def update_setting(key: str) -> Response:
    """Изменяет значение настройки."""

    payload = request.get_json(force=True)
    value = payload.get("value")
    setting = settings_service.set_setting(key, value)
    if key == "default_model_name" and value:
        model = ModelConfig.query.filter_by(name=value).first()
        if model:
            ModelConfig.query.update({ModelConfig.is_default: False})
            model.is_default = True
            db.session.commit()
        else:
            current_app.logger.warning("Модель %s не найдена при установке по умолчанию", value)
    return jsonify(setting.to_dict())


@admin_bp.route("/api/statistics", methods=["GET"])
def get_statistics() -> Response:
    """Возвращает статистику за указанный период."""

    period = request.args.get("period", "day")
    return jsonify(statistics.get_summary(period))


@admin_bp.route("/api/logs", methods=["GET"])
def get_logs() -> Response:
    """Возвращает последние записи лога."""

    limit = int(request.args.get("limit", 20))
    return jsonify(statistics.get_recent_logs(limit))


@admin_bp.route("/api/active-users", methods=["GET"])
def get_active_users() -> Response:
    """Возвращает список активных пользователей."""

    limit = int(request.args.get("limit", 20))
    return jsonify(statistics.get_active_users(limit))


@admin_bp.route("/api/bot/polling", methods=["POST"])
def start_bot_polling() -> Response:
    """Запускает бота в режиме polling."""

    try:
        bot_runner.bot_runner.start_polling()
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.exception("Не удалось запустить бота: %s", exc)
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify({"status": "started", "mode": "polling"})


@admin_bp.route("/api/bot/webhook", methods=["POST"])
def start_bot_webhook() -> Response:
    """Запускает бота в режиме webhook."""

    try:
        bot_runner.bot_runner.start_webhook()
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.exception("Не удалось запустить бота: %s", exc)
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify({"status": "started", "mode": "webhook"})


@admin_bp.route("/api/bot/stop", methods=["POST"])
def stop_bot() -> Response:
    """Останавливает телеграм-бота."""

    bot_runner.bot_runner.stop()
    return jsonify({"status": "stopped"})


@admin_bp.route("/api/bot/status", methods=["GET"])
def bot_status() -> Response:
    """Возвращает статус бота."""

    return jsonify(bot_runner.bot_runner.status())
