"""Database models for the ai_router application."""

from __future__ import annotations

import datetime as dt
from flask_sqlalchemy import SQLAlchemy

# Инициализация глобального объекта SQLAlchemy осуществляется здесь, чтобы
# модели можно было переиспользовать во всех частях приложения без циклических
# импортов.
db = SQLAlchemy()


class TimestampMixin:
    """Mixin, добавляющий полям временных меток значения по умолчанию."""

    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=dt.datetime.utcnow,
        onupdate=dt.datetime.utcnow,
        nullable=False,
    )


class User(db.Model, TimestampMixin):
    """Модель пользователя, взаимодействующего с LLM через Telegram."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    username = db.Column(db.String(255))
    full_name = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    subscription_plan = db.Column(db.String(32), default="free", nullable=False)
    tokens_used = db.Column(db.Integer, default=0, nullable=False)
    last_interaction = db.Column(db.DateTime)
    preferred_preset_id = db.Column(db.Integer, db.ForeignKey("model_presets.id"))

    conversations = db.relationship(
        "Conversation", back_populates="user", lazy="dynamic", cascade="all, delete"
    )
    logs = db.relationship(
        "RequestLog", back_populates="user", lazy="dynamic", cascade="all, delete"
    )
    preferred_preset = db.relationship("ModelPreset")


class AdminSetting(db.Model, TimestampMixin):
    """Настройки приложения, редактируемые через админ-панель."""

    __tablename__ = "admin_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(128), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)


class ModelPreset(db.Model, TimestampMixin):
    """Преднастроенные режимы работы модели."""

    __tablename__ = "model_presets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    display_name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    temperature = db.Column(db.Float, default=0.7, nullable=False)
    max_tokens = db.Column(db.Integer, default=512, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)

    conversations = db.relationship("Conversation", back_populates="preset", lazy="dynamic")
    logs = db.relationship("RequestLog", back_populates="preset", lazy="dynamic")


class Conversation(db.Model, TimestampMixin):
    """Диалог пользователя с моделью."""

    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    preset_id = db.Column(db.Integer, db.ForeignKey("model_presets.id"))
    ended_at = db.Column(db.DateTime)

    user = db.relationship("User", back_populates="conversations")
    preset = db.relationship("ModelPreset", back_populates="conversations")
    logs = db.relationship(
        "RequestLog", back_populates="conversation", lazy="dynamic", cascade="all, delete"
    )


class RequestLog(db.Model, TimestampMixin):
    """Лог запросов и ответов модели."""

    __tablename__ = "request_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    preset_id = db.Column(db.Integer, db.ForeignKey("model_presets.id"))
    prompt = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text)
    status = db.Column(db.String(32), default="pending", nullable=False)
    error_message = db.Column(db.Text)
    prompt_tokens = db.Column(db.Integer)
    completion_tokens = db.Column(db.Integer)
    total_tokens = db.Column(db.Integer)

    user = db.relationship("User", back_populates="logs")
    conversation = db.relationship("Conversation", back_populates="logs")
    preset = db.relationship("ModelPreset", back_populates="logs")


# Индексы для ускорения поиска по ключевым полям.
db.Index("ix_request_logs_created_at", RequestLog.created_at)
db.Index("ix_conversations_active", Conversation.is_active)
