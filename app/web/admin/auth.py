"""Маршруты аутентификации администратора."""

from __future__ import annotations

from typing import Optional, Union

from flask import Response, current_app, redirect, render_template, request, session, url_for

from . import ADMIN_SESSION_KEY, _safe_next_url, admin_bp


# NOTE[agent]: Маршрут отображает и обрабатывает форму входа в админку.
@admin_bp.route("/login", methods=["GET", "POST"])
def login() -> Union[Response, str]:
    """Авторизует администратора на основе настроек приложения."""

    error: Optional[str] = None
    app_login = current_app.config.get("ADMIN_LOGIN")
    app_password = current_app.config.get("ADMIN_PASSWORD")
    credentials_configured = bool(app_login and app_password)
    if request.method == "POST":
        if not credentials_configured:
            error = "Учётные данные администратора не настроены."
        else:
            form_login = request.form.get("login", "").strip()
            form_password = request.form.get("password", "")
            if form_login == app_login and form_password == app_password:
                session[ADMIN_SESSION_KEY] = True
                session["admin_login"] = form_login
                redirect_target = _safe_next_url(request.args.get("next"))
                return redirect(redirect_target)
            error = "Неверный логин или пароль."
    return render_template(
        "admin/login.html",
        error=error,
        credentials_configured=credentials_configured,
    )


# NOTE[agent]: Маршрут завершает сессию администратора.
@admin_bp.route("/logout")
def logout() -> Response:
    """Выходит из админ-панели и очищает сессию пользователя."""

    session.pop(ADMIN_SESSION_KEY, None)
    session.pop("admin_login", None)
    return redirect(url_for("admin.login"))
