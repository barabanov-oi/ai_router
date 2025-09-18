"""Сервисы статистики для админ-панели."""

from __future__ import annotations

import logging
from typing import Dict, List

from sqlalchemy import func

from ..models import Conversation, RequestLog, User

LOGGER = logging.getLogger(__name__)


# AGENT: Формирует сводную статистику по системе.
def get_summary_stats() -> Dict[str, int]:
    """Получить основные показатели работы системы.

    Returns:
        Dict[str, int]: Количество пользователей, диалогов и запросов.
    """

    total_users = User.query.count()
    active_users = User.query.filter(User.is_active.is_(True)).count()
    total_conversations = Conversation.query.count()
    total_requests = RequestLog.query.count()
    total_tokens = RequestLog.query.with_entities(func.sum(RequestLog.total_tokens)).scalar() or 0
    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_conversations": total_conversations,
        "total_requests": total_requests,
        "total_tokens": int(total_tokens),
    }


# AGENT: Собирает активность конкретного пользователя.
def get_user_stats(user_id: int) -> Dict[str, int]:
    """Получить статистику по отдельному пользователю.

    Args:
        user_id (int): Идентификатор пользователя.

    Returns:
        Dict[str, int]: Количество диалогов и запросов пользователя.
    """

    conversation_count = Conversation.query.filter_by(user_id=user_id).count()
    request_count = RequestLog.query.filter_by(user_id=user_id).count()
    token_sum = (
        RequestLog.query.with_entities(func.sum(RequestLog.total_tokens))
        .filter(RequestLog.user_id == user_id)
        .scalar()
        or 0
    )
    return {
        "conversation_count": conversation_count,
        "request_count": request_count,
        "total_tokens": int(token_sum),
    }


# AGENT: Возвращает последние записи журнала запросов.
def get_recent_logs(limit: int = 20) -> List[RequestLog]:
    """Получить последние записи журнала запросов пользователей.

    Args:
        limit (int): Максимальное число записей.

    Returns:
        List[RequestLog]: Коллекция последних логов.
    """

    return (
        RequestLog.query.order_by(RequestLog.created_at.desc()).limit(limit).all()
    )
