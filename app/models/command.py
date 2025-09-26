"""Модель для настраиваемых команд Telegram-бота."""

from __future__ import annotations

from datetime import datetime

from . import db


# NOTE[agent]: Модель хранит команды вида "/example" и заранее подготовленные ответы.
class BotCommand(db.Model):
    """Описание пользовательской команды и текста ответа."""

    __tablename__ = "bot_commands"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, unique=True)
    response_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # NOTE[agent]: Метод обновляет текст команды и фиксирует время изменения.
    def update(self, *, name: str | None = None, response_text: str | None = None) -> None:
        """Обновляет имя команды и ответ."""

        if name is not None:
            self.name = name
        if response_text is not None:
            self.response_text = response_text
        self.updated_at = datetime.utcnow()

    def __repr__(self) -> str:
        """Возвращает строковое представление команды."""

        return f"<BotCommand id={self.id} name={self.name!r}>"
