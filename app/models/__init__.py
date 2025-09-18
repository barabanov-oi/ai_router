"""Модели данных приложения."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Глобальный экземпляр SQLAlchemy должен быть инициализирован в фабрике приложения.
db = SQLAlchemy()


class TimestampMixin:
    """Миксин с временными метками создания и обновления."""

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class User(db.Model, TimestampMixin):
    """Пользователь телеграм-бота и административного интерфейса."""

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[str] = mapped_column(unique=True, nullable=False, index=True)
    username: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
    subscription_type: Mapped[str] = mapped_column(default="free", nullable=False)
    last_active_at: Mapped[datetime | None]

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    messages: Mapped[list["MessageLog"]] = relationship(back_populates="user")

    def to_dict(self) -> Dict[str, Any]:
        """Возвращает представление пользователя в виде словаря."""

        return {
            "id": self.id,
            "telegram_id": self.telegram_id,
            "username": self.username,
            "is_active": self.is_active,
            "is_admin": self.is_admin,
            "subscription_type": self.subscription_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_active_at": self.last_active_at.isoformat() if self.last_active_at else None,
        }


class ModelConfig(db.Model, TimestampMixin):
    """Настройки отдельной модели LLM."""

    __tablename__ = "model_configs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(nullable=False)
    api_key: Mapped[str] = mapped_column(nullable=False)
    base_url: Mapped[str | None]
    model: Mapped[str] = mapped_column(nullable=False)
    temperature: Mapped[float] = mapped_column(default=0.7, nullable=False)
    max_tokens: Mapped[int | None]
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="model")

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует настройки модели к словарю для API."""

        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class Conversation(db.Model, TimestampMixin):
    """Активный или завершённый диалог пользователя с моделью."""

    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id"), nullable=False, index=True)
    model_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("model_configs.id"), nullable=True, index=True
    )
    mode: Mapped[str] = mapped_column(default="detailed", nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    ended_at: Mapped[datetime | None]

    user: Mapped[User] = relationship(back_populates="conversations")
    model: Mapped[ModelConfig | None] = relationship(back_populates="conversations")
    messages: Mapped[list["MessageLog"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует диалог в словарь."""

        return {
            "id": self.id,
            "user_id": self.user_id,
            "model_id": self.model_id,
            "mode": self.mode,
            "is_active": self.is_active,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }


class MessageLog(db.Model, TimestampMixin):
    """Лог отдельного сообщения диалога."""

    __tablename__ = "message_logs"
    __table_args__ = (UniqueConstraint("conversation_id", "message_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        db.ForeignKey("conversations.id"), nullable=False, index=True
    )
    message_index: Mapped[int] = mapped_column(nullable=False)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id"), nullable=False)
    user_message: Mapped[str] = mapped_column(nullable=False)
    assistant_response: Mapped[str | None]
    request_timestamp: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    response_timestamp: Mapped[datetime | None]
    mode: Mapped[str] = mapped_column(default="detailed", nullable=False)
    token_usage: Mapped[int | None]

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    user: Mapped[User] = relationship(back_populates="messages")

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует запись лога сообщения в словарь."""

        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_index": self.message_index,
            "user_id": self.user_id,
            "user_message": self.user_message,
            "assistant_response": self.assistant_response,
            "request_timestamp": self.request_timestamp.isoformat(),
            "response_timestamp": self.response_timestamp.isoformat()
            if self.response_timestamp
            else None,
            "mode": self.mode,
            "token_usage": self.token_usage,
        }


class Setting(db.Model, TimestampMixin):
    """Глобальные настройки приложения в формате ключ-значение."""

    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True, nullable=False)
    value: Mapped[str | None]

    def to_dict(self) -> Dict[str, Any]:
        """Возвращает настройку в формате словаря."""

        return {"key": self.key, "value": self.value}
