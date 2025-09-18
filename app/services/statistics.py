"""Сервисы для расчёта статистики."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from sqlalchemy import func

from app.models import MessageLog, User, db


PERIOD_MAP = {
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}
"""Периоды, доступные для выборки статистики."""


def _period_start(period: str) -> datetime:
    """Возвращает временную отметку начала периода."""

    delta = PERIOD_MAP.get(period, PERIOD_MAP["day"])
    return datetime.utcnow() - delta


def get_summary(period: str) -> Dict[str, int]:
    """Возвращает агрегированную статистику за период."""

    start = _period_start(period)
    query = MessageLog.query.filter(MessageLog.request_timestamp >= start)
    total_requests = query.count()
    total_tokens = (
        db.session.query(func.coalesce(func.sum(MessageLog.token_usage), 0))
        .filter(MessageLog.request_timestamp >= start)
        .scalar()
    )
    active_users = (
        db.session.query(func.count(func.distinct(MessageLog.user_id)))
        .filter(MessageLog.request_timestamp >= start)
        .scalar()
    )
    return {
        "total_requests": total_requests,
        "total_tokens": int(total_tokens or 0),
        "active_users": active_users,
    }


def get_recent_logs(limit: int = 20) -> List[dict]:
    """Возвращает последние записи лога."""

    logs = (
        MessageLog.query.order_by(MessageLog.request_timestamp.desc())
        .limit(limit)
        .all()
    )
    return [log.to_dict() for log in logs]


def get_active_users(limit: int = 20) -> List[dict]:
    """Возвращает активных пользователей."""

    users = User.query.order_by(User.last_active_at.desc().nullslast()).limit(limit).all()
    return [user.to_dict() for user in users]
