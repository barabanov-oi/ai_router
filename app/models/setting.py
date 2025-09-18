"""Глобальные настройки приложения."""

from datetime import datetime

from . import db


# NOTE[agent]: Таблица хранит произвольные настройки в формате ключ/значение.
class AppSetting(db.Model):
    """Сохраняет настройку приложения."""

    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(128), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # NOTE[agent]: Обновление значения настройки фиксирует время изменения.
    def update_value(self, new_value: str) -> None:
        """Изменяет значение настройки и обновляет время модификации."""

        self.value = new_value
        self.updated_at = datetime.utcnow()

    def __repr__(self) -> str:
        """Возвращает строковое представление настройки."""

        return f"<AppSetting key={self.key}>"
