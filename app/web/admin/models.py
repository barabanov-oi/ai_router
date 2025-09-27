"""Маршруты управления конфигурациями моделей."""

from __future__ import annotations

from typing import Optional, Union

from flask import Response, current_app, render_template, request

from ...models import LLMProvider, ModelConfig, db
from ...services.settings_service import SettingsService
from . import admin_bp


# NOTE[agent]: Управление конфигурациями моделей и выбор активной.
@admin_bp.route("/models", methods=["GET", "POST"])
def manage_models() -> Union[Response, str]:
    """Позволяет добавлять новые модели и выбирать активную."""

    settings_service = SettingsService()
    if request.method == "POST":
        action = request.form.get("action", "create")
        name = request.form.get("name", "").strip()
        model_name = request.form.get("model", "").strip()
        instruction = request.form.get("system_instruction", "").strip() or None

        # NOTE[agent]: Вспомогательная функция безопасно преобразует значение в float.
        def _float(field: str, default: float) -> float:
            """Возвращает значение поля как float или значение по умолчанию."""

            value = request.form.get(field, "")
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        # NOTE[agent]: Вспомогательная функция безопасно преобразует значение в int.
        def _int(field: str, default: int) -> int:
            """Возвращает значение поля как int или значение по умолчанию."""

            value = request.form.get(field, "")
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        temperature = _float("temperature", 1.0)
        max_tokens = _int("max_tokens", 512)
        dialog_token_limit = _int("dialog_token_limit", 20000)
        top_p = _float("top_p", 1.0)
        is_default = request.form.get("is_default") == "on"
        provider_id_raw = request.form.get("provider_id")
        provider: Optional[LLMProvider] = None
        try:
            provider_id = int(provider_id_raw) if provider_id_raw else None
        except (TypeError, ValueError):
            provider_id = None
        if provider_id is not None:
            provider = LLMProvider.query.get(provider_id)
            if provider is None:
                current_app.logger.warning("Поставщик с id=%s не найден", provider_id)

        if action == "create" and name and model_name and provider:
            if is_default:
                ModelConfig.query.update({ModelConfig.is_default: False})
            model = ModelConfig(
                name=name,
                model=model_name,
                provider=provider,
                temperature=temperature,
                max_tokens=max_tokens,
                dialog_token_limit=dialog_token_limit,
                top_p=top_p,
                system_instruction=instruction,
                is_default=is_default,
            )
            db.session.add(model)
            db.session.commit()
            if is_default:
                settings_service.set("active_model_id", str(model.id))
        elif action == "create" and not provider:
            current_app.logger.warning("Не удалось создать модель %s: не выбран поставщик", name)
        elif action == "update":
            model_id_raw = request.form.get("model_id")
            model_obj: Optional[ModelConfig] = None
            try:
                model_id = int(model_id_raw) if model_id_raw else None
            except (TypeError, ValueError):
                model_id = None
            if model_id is not None:
                model_obj = ModelConfig.query.get(model_id)
            if model_obj:
                model_obj.name = name or model_obj.name
                model_obj.model = model_name or model_obj.model
                if provider:
                    model_obj.provider = provider
                model_obj.temperature = temperature
                model_obj.max_tokens = max_tokens
                model_obj.dialog_token_limit = dialog_token_limit
                model_obj.top_p = top_p
                model_obj.system_instruction = instruction
                if is_default:
                    ModelConfig.query.update({ModelConfig.is_default: False})
                    model_obj.is_default = True
                else:
                    model_obj.is_default = False
                db.session.commit()
                if is_default:
                    settings_service.set("active_model_id", str(model_obj.id))
                else:
                    current_active = settings_service.get("active_model_id")
                    if current_active and current_active == str(model_obj.id):
                        settings_service.set("active_model_id", "")
    models = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    providers = LLMProvider.query.order_by(LLMProvider.name.asc()).all()
    provider_titles = LLMProvider.vendor_titles()
    active_model_id = settings_service.get("active_model_id")
    return render_template(
        "admin/models.html",
        models=models,
        active_model_id=active_model_id,
        providers=providers,
        provider_titles=provider_titles,
    )
