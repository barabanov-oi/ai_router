"""Маршруты административного интерфейса."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from flask import Blueprint, Response, redirect, request, session, url_for


admin_bp = Blueprint("admin", __name__, url_prefix="/admin", template_folder="../templates")


# NOTE[agent]: Ключ сессии, сигнализирующий об авторизованном администраторе.
ADMIN_SESSION_KEY = "admin_authenticated"


# NOTE[agent]: Обработчик проверяет доступ к маршрутам админ-панели.
@admin_bp.before_request
def ensure_authenticated() -> Optional[Response]:
    """Перенаправляет неавторизованных пользователей на форму входа."""

    endpoint = request.endpoint or ""
    if endpoint.endswith("login") or endpoint.endswith("logout"):
        return None
    if _is_admin_authenticated():
        return None
    next_url = request.url
    return redirect(url_for("admin.login", next=next_url))


# NOTE[agent]: Вспомогательная функция проверяет авторизацию в сессии.
def _is_admin_authenticated() -> bool:
    """Сообщает, авторизован ли администратор в текущей сессии."""

    return bool(session.get(ADMIN_SESSION_KEY))


# NOTE[agent]: Вспомогательная функция защищает редирект после логина.
def _safe_next_url(next_url: Optional[str]) -> str:
    """Возвращает безопасный относительный URL для перенаправления."""

    default_url = url_for("admin.dashboard")
    if not next_url:
        return default_url
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return default_url
    if not parsed.path.startswith("/admin"):
        return default_url
    return next_url


from . import api, auth, commands, dashboard, dialogs, logs, models, providers, settings, users  # noqa: E402,F401

__all__ = ["admin_bp"]
