"""Маршруты управления пользовательскими командами бота."""

from __future__ import annotations

from typing import Union

from flask import Response, current_app, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from ...models import BotCommand, db
from . import admin_bp


# NOTE[agent]: Управление пользовательскими командами Telegram-бота.
@admin_bp.route("/commands", methods=["GET", "POST"])
def manage_commands() -> Union[Response, str]:
    """Позволяет добавить или отредактировать команды вида '/example'."""

    if request.method == "POST":
        action = request.form.get("action", "create")
        command_raw = (request.form.get("command", "") or "").strip()
        response_text = (request.form.get("response", "") or "").strip()
        normalized = command_raw.lstrip("/")
        if " " in normalized:
            normalized = normalized.split()[0]
        normalized = normalized.lower()

        if action == "delete":
            command_id_raw = request.form.get("command_id")
            try:
                command_id = int(command_id_raw) if command_id_raw else None
            except (TypeError, ValueError):
                command_id = None
            command = None
            if command_id is not None:
                try:
                    command = BotCommand.query.get(command_id)
                except SQLAlchemyError as exc:
                    current_app.logger.warning("Ошибка при поиске команды: %s", exc)
                    db.session.rollback()
            if command:
                try:
                    db.session.delete(command)
                    db.session.commit()
                except SQLAlchemyError as exc:
                    db.session.rollback()
                    current_app.logger.warning("Не удалось удалить команду %s: %s", command_id_raw, exc)
            else:
                current_app.logger.warning("Не удалось удалить команду: id=%s", command_id_raw)
            return redirect(url_for("admin.manage_commands"))

        if not normalized:
            current_app.logger.warning("Команда не указана или указана некорректно")
        elif not response_text:
            current_app.logger.warning("Не задан ответ для команды %s", command_raw)
        else:
            try:
                existing = BotCommand.query.filter_by(name=normalized).first()
            except SQLAlchemyError as exc:
                existing = None
                current_app.logger.warning("Ошибка при поиске команды %s: %s", normalized, exc)
                db.session.rollback()
            if action == "update":
                command_id_raw = request.form.get("command_id")
                try:
                    command_id = int(command_id_raw) if command_id_raw else None
                except (TypeError, ValueError):
                    command_id = None
                command = None
                if command_id is not None:
                    try:
                        command = BotCommand.query.get(command_id)
                    except SQLAlchemyError as exc:
                        current_app.logger.warning(
                            "Ошибка при загрузке команды id=%s: %s", command_id_raw, exc
                        )
                        db.session.rollback()
                if not command:
                    current_app.logger.warning(
                        "Не удалось обновить команду: id=%s не найден", command_id_raw
                    )
                else:
                    conflict = None
                    if existing and existing.id != command.id:
                        conflict = existing
                    if conflict:
                        current_app.logger.warning(
                            "Конфликт имён команд: %s уже используется", normalized
                        )
                    else:
                        try:
                            command.update(name=normalized, response_text=response_text)
                            db.session.commit()
                        except SQLAlchemyError as exc:
                            db.session.rollback()
                            current_app.logger.warning(
                                "Ошибка при обновлении команды %s: %s", normalized, exc
                            )
                        return redirect(url_for("admin.manage_commands"))
            else:
                if existing:
                    try:
                        existing.update(response_text=response_text)
                        db.session.commit()
                    except SQLAlchemyError as exc:
                        db.session.rollback()
                        current_app.logger.warning(
                            "Ошибка при обновлении ответа команды %s: %s", normalized, exc
                        )
                else:
                    try:
                        command = BotCommand(name=normalized, response_text=response_text)
                        db.session.add(command)
                        db.session.commit()
                    except SQLAlchemyError as exc:
                        db.session.rollback()
                        current_app.logger.warning(
                            "Ошибка при создании команды %s: %s", normalized, exc
                        )
                return redirect(url_for("admin.manage_commands"))

    try:
        commands = BotCommand.query.order_by(BotCommand.name.asc()).all()
    except SQLAlchemyError as exc:
        current_app.logger.warning("Ошибка при загрузке списка команд: %s", exc)
        db.session.rollback()
        commands = []
    return render_template("admin/commands.html", commands=commands)
