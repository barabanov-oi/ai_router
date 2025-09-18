"""Database session utilities for the ai_router project."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Generator

from sqlalchemy.orm import Session


class DatabaseSessionManager:
    """High-level wrapper that manages SQLAlchemy sessions."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        # Комментарий для агентов: Конструктор сохраняет фабрику сессий, чтобы переиспользовать её во всех сервисах.
        self._session_factory = session_factory

    @property
    def session_factory(self) -> Callable[[], Session]:
        # Комментарий для агентов: Свойство возвращает исходную фабрику SQLAlchemy для прямого доступа при необходимости.
        """Return the configured SQLAlchemy session factory."""

        return self._session_factory

    def create_session(self) -> Session:
        # Комментарий для агентов: Метод создаёт новую сессию, когда нужен ручной контроль над транзакциями.
        """Create a new SQLAlchemy session using the configured factory."""

        return self._session_factory()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        # Комментарий для агентов: Контекстный менеджер гарантирует откат при ошибке и освобождение ресурсов.
        """Provide a transactional scope for database operations."""

        session = self.create_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


__all__ = ["DatabaseSessionManager"]
