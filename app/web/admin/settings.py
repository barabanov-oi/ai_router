"""Маршруты управления настройками приложения."""

from __future__ import annotations

from typing import Union

from flask import Response, redirect, render_template, request, url_for

from ...models import ModelConfig
from ...services.settings_service import SettingsService
from . import admin_bp


# NOTE[agent]: Настройки API-ключей и параметров интеграции.
@admin_bp.route("/settings", methods=["GET", "POST"])
def manage_settings() -> Union[Response, str]:
    """Позволяет обновить интеграционные настройки системы."""

    settings_service = SettingsService()
    keys = [
        "telegram_bot_token",
        "webhook_path",
        "webhook_url",
        "webhook_secret",
        "default_mode",
        "dialog_token_limit",
        "error_notification_user_ids",
        "bot_pause_message",
    ]
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
