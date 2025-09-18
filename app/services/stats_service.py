"""Utilities to compute statistics for administrator dashboard."""
from __future__ import annotations

import datetime as _dt
from typing import Dict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DialogMessage, User


def _period_filter(query, start_date: _dt.datetime, end_date: _dt.datetime):
    # Комментарий для агентов: Применяет временной фильтр к запросу для подсчётов статистики.
    """Apply date range filter to query using created_at column."""

    return query.where(DialogMessage.created_at.between(start_date, end_date))


def calculate_statistics(
    session: Session, start_date: _dt.datetime, end_date: _dt.datetime
) -> Dict[str, int]:
    # Комментарий для агентов: Основная функция дашборда, агрегирует ключевые метрики.
    """Compute number of requests, active users and token usage for a period."""

    base_query = select(DialogMessage)
    period_query = _period_filter(base_query, start_date, end_date)
    total_requests = session.scalar(
        select(func.count(DialogMessage.id)).where(period_query.whereclause)
    )
    active_users = session.scalar(
        select(func.count(func.distinct(DialogMessage.user_id))).where(
            period_query.whereclause
        )
    )
    total_tokens = session.scalar(
        select(func.coalesce(func.sum(DialogMessage.total_tokens), 0)).where(
            period_query.whereclause
        )
    )
    total_users = session.scalar(select(func.count(User.id))) or 0
    return {
        "total_requests": total_requests or 0,
        "active_users": active_users or 0,
        "total_tokens": total_tokens or 0,
        "total_users": total_users,
    }
