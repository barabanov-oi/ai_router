"""Маршруты управления пользователями."""

from __future__ import annotations

from typing import Union

from flask import Response, redirect, render_template, url_for

from ...models import User, db
from . import admin_bp


# NOTE[agent]: Страница управления пользователями позволяет изменять активность.
@admin_bp.route("/users", methods=["GET"])
def manage_users() -> Union[Response, str]:
    """Отображает список пользователей."""

    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)


# NOTE[agent]: Маршрут переключает флаг активности пользователя.
@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
def toggle_user(user_id: int) -> Response:
    """Переключает доступ пользователя к боту."""

    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    return redirect(url_for("admin.manage_users"))
