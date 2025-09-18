"""ORM-модель пользователя Telegram."""

from datetime import datetime

from . import db


# NOTE[agent]: Класс описывает пользователей, взаимодействующих с ботом и админкой.
class User(db.Model):
    """Модель пользователя, зарегистрированного в системе.

    Атрибуты:
        id: Идентификатор пользователя в базе данных.
        telegram_id: Уникальный идентификатор пользователя в Telegram.
        username: Имя пользователя в Telegram.
        full_name: Полное имя пользователя.
        is_active: Флаг активности (доступ к боту).
        is_admin: Флаг доступа к админке.
        preferred_mode: Выбранный режим генерации ответов LLM.
        created_at: Дата создания записи.
        last_active_at: Дата последней активности пользователя.
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.String(64), unique=True, nullable=False)
    username = db.Column(db.String(255), nullable=True)
    full_name = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    preferred_mode = db.Column(db.String(64), default="default", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_active_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    dialogs = db.relationship("Dialog", backref="user", lazy=True)
    messages = db.relationship("MessageLog", backref="user", lazy=True)

    # NOTE[agent]: Метод обновляет таймстемп активности пользователя.
    def touch(self) -> None:
        """Обновляет время последней активности пользователя."""

        self.last_active_at = datetime.utcnow()

    def __repr__(self) -> str:
        """Возвращает строковое представление модели."""

        return f"<User id={self.id} telegram_id={self.telegram_id}>"
