"""Database models for the ai_router project."""
from __future__ import annotations

import datetime as _dt
from typing import List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()


class TimestampMixin:
    """Mixin that adds timestamp fields for creation and update events."""

    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime,
        default=_dt.datetime.utcnow,
        onupdate=_dt.datetime.utcnow,
        nullable=False,
    )


class User(TimestampMixin, Base):
    """Database model that stores Telegram user metadata."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dialog_mode: Mapped[str] = mapped_column(String(64), default="standard", nullable=False)
    token_quota: Mapped[Optional[int]] = mapped_column(Integer)
    last_seen_at: Mapped[Optional[_dt.datetime]] = mapped_column(DateTime)

    dialogs: Mapped[List["Dialog"]] = relationship(
        "Dialog", back_populates="user", cascade="all, delete-orphan"
    )

    # Комментарий для агентов: Метод формирует понятное представление пользователя для логов и отладки.
    def __repr__(self) -> str:
        return f"<User id={self.id} telegram_id={self.telegram_id}>"


class ModelConfig(TimestampMixin, Base):
    """Database model that stores OpenAI model configuration."""

    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    api_key: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[Optional[str]] = mapped_column(String(255))
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    dialog_messages: Mapped[List["DialogMessage"]] = relationship(
        "DialogMessage", back_populates="model_config"
    )

    # Комментарий для агентов: Метод сообщает человеко-читаемое имя конфигурации модели.
    def __repr__(self) -> str:
        return f"<ModelConfig id={self.id} name={self.name}>"


class BotSettings(TimestampMixin, Base):
    """Model that stores Telegram bot configuration settings."""

    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_token: Mapped[Optional[str]] = mapped_column(String(255))
    webhook_url: Mapped[Optional[str]] = mapped_column(String(255))
    webhook_secret: Mapped[Optional[str]] = mapped_column(String(255))
    use_webhook: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active_model_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("model_configs.id"), nullable=True
    )

    active_model: Mapped[Optional[ModelConfig]] = relationship("ModelConfig")

    # Комментарий для агентов: Метод помогает отображать настройки бота в логах.
    def __repr__(self) -> str:
        return f"<BotSettings id={self.id} use_webhook={self.use_webhook}>"


class Dialog(TimestampMixin, Base):
    """Model that stores information about a chat dialog between user and LLM."""

    __tablename__ = "dialogs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="Новый диалог", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="dialogs")
    messages: Mapped[List["DialogMessage"]] = relationship(
        "DialogMessage", back_populates="dialog", cascade="all, delete-orphan"
    )

    # Комментарий для агентов: Метод уточняет параметры диалога при выводе в консоль.
    def __repr__(self) -> str:
        return f"<Dialog id={self.id} user_id={self.user_id} active={self.is_active}>"


class DialogMessage(TimestampMixin, Base):
    """Model that stores user questions and assistant answers inside a dialog."""

    __tablename__ = "dialog_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dialog_id: Mapped[int] = mapped_column(Integer, ForeignKey("dialogs.id"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    user_text: Mapped[str] = mapped_column(Text, nullable=False)
    user_sent_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, nullable=False
    )
    assistant_text: Mapped[Optional[str]] = mapped_column(Text)
    assistant_sent_at: Mapped[Optional[_dt.datetime]] = mapped_column(DateTime)
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    model_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("model_configs.id"), nullable=True
    )

    dialog: Mapped[Dialog] = relationship("Dialog", back_populates="messages")
    model_config: Mapped[Optional[ModelConfig]] = relationship(
        "ModelConfig", back_populates="dialog_messages"
    )

    # Комментарий для агентов: Метод делает логирование отдельных сообщений более информативным.
    def __repr__(self) -> str:
        return f"<DialogMessage id={self.id} dialog_id={self.dialog_id} seq={self.sequence_number}>"


__all__ = [
    "Base",
    "BotSettings",
    "Dialog",
    "DialogMessage",
    "ModelConfig",
    "User",
]
