"""Настройки моделей LLM."""

from datetime import datetime

from . import db


# NOTE[agent]: Модель описывает возможные конфигурации моделей OpenAI.
class ModelConfig(db.Model):
    """Хранит параметры модели LLM для переключения в админке."""

    __tablename__ = "model_configs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    model = db.Column(db.String(128), nullable=False)
    temperature = db.Column(db.Float, default=1.0, nullable=False)
    max_tokens = db.Column(db.Integer, default=512, nullable=False)
    top_p = db.Column(db.Float, default=1.0, nullable=False)
    frequency_penalty = db.Column(db.Float, default=0.0, nullable=False)
    presence_penalty = db.Column(db.Float, default=0.0, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # NOTE[agent]: Метод возвращает словарь параметров для OpenAI API.
    def to_openai_kwargs(self) -> dict:
        """Готовит словарь параметров для вызова OpenAI API."""

        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
        }

    def __repr__(self) -> str:
        """Возвращает строковое представление конфигурации модели."""

        return f"<ModelConfig id={self.id} name={self.name} default={self.is_default}>"
