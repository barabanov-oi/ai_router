"""ORM-модель диалога между пользователем и LLM."""

from datetime import datetime

from . import db


# NOTE[agent]: Модель хранит состояние диалога для сохранения контекста.
class Dialog(db.Model):
    """Содержит метаданные диалога пользователя с моделью."""

    __tablename__ = "dialogs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    telegram_chat_id = db.Column(db.String(64), nullable=True)

    messages = db.relationship("MessageLog", backref="dialog", lazy=True)

    # NOTE[agent]: Метод завершает диалог и фиксирует время окончания.
    def close(self) -> None:
        """Помечает диалог завершённым."""

        self.is_active = False
        self.ended_at = datetime.utcnow()

    def __repr__(self) -> str:
        """Возвращает строковое представление диалога."""

        return f"<Dialog id={self.id} user_id={self.user_id} active={self.is_active}>"
