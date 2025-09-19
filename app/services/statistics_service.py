"""Сервис формирования статистики для админки."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func

from ..models import Dialog, MessageLog, User, db


# NOTE[agent]: Класс агрегирует статистику по активности пользователей и токенам.
class StatisticsService:
    """Предоставляет метод для получения статистических данных."""

    def __init__(self) -> None:
        """Конструктор не содержит логики, добавлен для единообразия."""

    # NOTE[agent]: Метод считает ключевые метрики за указанный период.
    def gather(self, days: int = 7, start: datetime | None = None, end: datetime | None = None) -> dict[str, int]:
        """Вычисляет статистику за выбранный период.

        Args:
            days: Количество дней для анализа, если не задана пара дат.
            start: Дата и время начала периода.
            end: Дата и время окончания периода.

        Returns:
            Словарь метрик: количество запросов, пользователей, токенов.
        """

        if start and end and end < start:
            start, end = end, start

        now = datetime.utcnow()
        since = start or (now - timedelta(days=days))
        until = end or now

        total_users = User.query.count()
        active_users = (
            User.query.filter(User.last_active_at.between(since, until)).count()
        )
        query_count = (
            MessageLog.query.filter(
                MessageLog.created_at >= since,
                MessageLog.created_at <= until,
            ).count()
        )
        tokens_spent = (
            db.session.query(func.sum(MessageLog.tokens_used))
            .filter(
                MessageLog.created_at >= since,
                MessageLog.created_at <= until,
            )
            .scalar()
            or 0
        )
        open_dialogs = Dialog.query.filter_by(is_active=True).count()
        return {
            "total_users": total_users,
            "active_users": active_users,
            "query_count": query_count,
            "tokens_spent": int(tokens_spent),
            "open_dialogs": open_dialogs,
        }
