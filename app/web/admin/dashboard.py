"""Маршрут дашборда админ-панели."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask import current_app, render_template, request

from ...bot.bot_service import TelegramBotManager
from ...models import LLMProvider, ModelConfig
from ...services.settings_service import SettingsService
from ...services.statistics_service import StatisticsService
from . import admin_bp


# NOTE[agent]: Точка входа в админку отображает ключевые метрики и статус бота.
@admin_bp.route("/")
def dashboard() -> str:
    """Отображает сводную статистику и основные настройки."""

    period = int(request.args.get("days", 7) or 7)
    start_raw = request.args.get("start")
    end_raw = request.args.get("end")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    if start_raw and end_raw:
        try:
            start_date = datetime.strptime(start_raw, "%Y-%m-%d")
            end_date = datetime.strptime(end_raw, "%Y-%m-%d")
            if end_date < start_date:
                start_date, end_date = end_date, start_date
        except ValueError:
            start_date = None
            end_date = None
    stats = StatisticsService().gather(days=period, start=start_date, end=end_date)
    selected_period_days = period
    if start_date and end_date:
        selected_period_days = (end_date - start_date).days + 1
    settings = SettingsService().all_settings()
    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    is_bot_running = bot_manager.is_running() if bot_manager else False
    models = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    provider_titles = LLMProvider.vendor_titles()
    active_model = None
    active_model_id = settings.get("active_model_id", "")
    for model in models:
        if active_model_id and str(model.id) == active_model_id:
            active_model = model
            break
    if active_model is None:
        active_model = next((model for model in models if model.is_default), None)
    start_value = start_date.strftime("%Y-%m-%d") if start_date else ""
    end_value = end_date.strftime("%Y-%m-%d") if end_date else ""
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        period=period,
        start_date=start_date,
        end_date=end_date,
        selected_period_days=selected_period_days,
        settings=settings,
        is_bot_running=is_bot_running,
        models=models,
        active_model=active_model,
        start_value=start_value,
        end_value=end_value,
        provider_titles=provider_titles,
    )
