"""Маршруты управления диалогами пользователей."""

from __future__ import annotations

from flask import Response, redirect, url_for

from ...models import Dialog, db
from . import admin_bp


# NOTE[agent]: Маршрут завершает диалог пользователя из админки.
@admin_bp.route("/dialogs/<int:dialog_id>/close", methods=["POST"])
def close_dialog(dialog_id: int) -> Response:
    """Помечает диалог закрытым."""

    dialog = Dialog.query.get_or_404(dialog_id)
    dialog.close()
    db.session.commit()
    return redirect(url_for("admin.logs"))
