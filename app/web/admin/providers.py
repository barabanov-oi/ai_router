"""Маршруты управления провайдерами LLM."""

from __future__ import annotations

from typing import Union

from flask import Response, current_app, render_template, request

from ...models import LLMProvider, db
from . import admin_bp


# NOTE[agent]: Управление поставщиками LLM и их API-ключами.
@admin_bp.route("/providers", methods=["GET", "POST"])
def manage_providers() -> Union[Response, str]:
    """Позволяет добавлять и редактировать поставщиков API."""

    vendor_choices = list(LLMProvider.allowed_vendors())
    allowed_vendors = set(vendor_choices)
    vendor_titles = LLMProvider.vendor_titles()

    if request.method == "POST":
        action = request.form.get("action", "create")
        vendor = (request.form.get("vendor", "") or "").strip().lower()
        name = request.form.get("name", "").strip()
        api_key = request.form.get("api_key", "").strip()

        if action == "create":
            if vendor not in allowed_vendors:
                current_app.logger.warning("Не удалось создать провайдера: неизвестный тип %s", vendor)
            else:
                provider_name = name or vendor_titles.get(vendor, vendor.title())
                provider = LLMProvider(name=provider_name, vendor=vendor, api_key=api_key)
                db.session.add(provider)
                db.session.commit()
        elif action == "update":
            provider_id_raw = request.form.get("provider_id")
            try:
                provider_id = int(provider_id_raw) if provider_id_raw else None
            except (TypeError, ValueError):
                provider_id = None
            provider = LLMProvider.query.get(provider_id) if provider_id is not None else None
            if not provider:
                current_app.logger.warning("Не удалось обновить провайдера: id=%s не найден", provider_id_raw)
            else:
                if vendor and vendor in allowed_vendors:
                    provider.vendor = vendor
                elif vendor:
                    current_app.logger.warning("Игнорируем неизвестный тип провайдера: %s", vendor)
                new_name = name or provider.name
                provider.update_credentials(name=new_name, api_key=api_key)
                db.session.commit()

    providers = LLMProvider.query.order_by(LLMProvider.created_at.desc()).all()
    return render_template(
        "admin/providers.html",
        providers=providers,
        vendor_titles=vendor_titles,
        vendor_choices=vendor_choices,
    )
