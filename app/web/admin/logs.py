"""Маршруты просмотра логов и диалогов."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import render_template, request
from sqlalchemy import func

from ...models import Dialog, MessageLog, User, db
from . import admin_bp


# NOTE[agent]: Страница с журналом сообщений для аудита.
@admin_bp.route("/logs")
def logs() -> str:
    """Показывает последние сообщения пользователей и ответы LLM."""

    limit = int(request.args.get("limit", 50) or 50)
    dialog_limit = int(request.args.get("dialog_limit", 50) or 50)
    message_stats = (
        db.session.query(
            MessageLog.dialog_id.label("dialog_id"),
            func.count(MessageLog.id).label("message_count"),
            func.coalesce(func.sum(MessageLog.tokens_used), 0).label("tokens_spent"),
            func.coalesce(func.sum(MessageLog.prompt_tokens), 0).label("prompt_tokens_spent"),
            func.coalesce(func.sum(MessageLog.completion_tokens), 0).label("completion_tokens_spent"),
        )
        .group_by(MessageLog.dialog_id)
        .subquery()
    )
    first_message_subquery = (
        db.session.query(MessageLog.user_message)
        .filter(MessageLog.dialog_id == Dialog.id)
        .order_by(MessageLog.message_index.asc())
        .limit(1)
        .correlate(Dialog)
        .scalar_subquery()
    )
    dialog_rows = (
        db.session.query(
            Dialog.id.label("dialog_id"),
            Dialog.is_active,
            User.username,
            User.telegram_id,
            func.coalesce(message_stats.c.message_count, 0).label("message_count"),
            func.coalesce(message_stats.c.tokens_spent, 0).label("tokens_spent"),
            func.coalesce(message_stats.c.prompt_tokens_spent, 0).label("prompt_tokens_spent"),
            func.coalesce(message_stats.c.completion_tokens_spent, 0).label("completion_tokens_spent"),
            first_message_subquery.label("first_message"),
        )
        .join(User, Dialog.user_id == User.id)
        .outerjoin(message_stats, message_stats.c.dialog_id == Dialog.id)
        .order_by(Dialog.started_at.desc())
        .limit(dialog_limit)
        .all()
    )
    dialog_logs: List[Dict[str, Any]] = []
    for row in dialog_rows:
        base_title = row.first_message or ""
        title = base_title[:15]
        if base_title and len(base_title) > 15:
            title = f"{title}…"
        if not title:
            title = f"Диалог #{row.dialog_id}"
        login = row.username or row.telegram_id or "—"
        dialog_logs.append(
            {
                "id": row.dialog_id,
                "title": title,
                "full_title": base_title,
                "message_count": int(row.message_count or 0),
                "tokens_spent": int(row.tokens_spent or 0),
                "input_tokens": int(row.prompt_tokens_spent or 0),
                "output_tokens": int(row.completion_tokens_spent or 0),
                "username": login,
                "is_active": row.is_active,
            }
        )

    # NOTE[agent]: Функция формирует краткое представление текста для таблицы логов.
    def _make_preview(text: Optional[str]) -> Tuple[str, bool, bool, str]:
        """Возвращает укороченную версию текста и метаданные для отображения."""

        if not text:
            return "—", False, False, ""
        preview_limit = 150
        is_long = len(text) > preview_limit
        preview = text if not is_long else f"{text[:preview_limit]}..."
        return preview, True, is_long, text

    records = (
        MessageLog.query.order_by(MessageLog.created_at.desc())
        .limit(limit)
        .all()
    )

    message_rows: List[Dict[str, Any]] = []
    for record in records:
        user_preview, has_user_text, user_truncated, user_full = _make_preview(record.user_message)
        llm_preview, has_llm_text, llm_truncated, llm_full = _make_preview(record.llm_response)
        created_at_value = record.created_at
        created_at_formatted = "—"
        if isinstance(created_at_value, datetime):
            created_at_formatted = created_at_value.strftime("%d.%m.%Y")
        message_rows.append(
            {
                "id": record.id,
                "dialog_id": record.dialog_id,
                "message_index": int(record.message_index or 0),
                "username": record.user.username or record.user.telegram_id or "—",
                "user_message_preview": user_preview,
                "user_message_full": user_full,
                "user_message_present": has_user_text,
                "user_message_truncated": user_truncated,
                "llm_response_preview": llm_preview,
                "llm_response_full": llm_full,
                "llm_response_present": has_llm_text,
                "llm_response_truncated": llm_truncated,
                "tokens_used": int(record.tokens_used or 0),
                "input_tokens": int(record.prompt_tokens or 0),
                "output_tokens": int(record.completion_tokens or 0),
                "created_at": created_at_formatted,
            }
        )
    return render_template(
        "admin/logs.html",
        message_rows=message_rows,
        limit=limit,
        dialog_logs=dialog_logs,
        dialog_limit=dialog_limit,
    )
