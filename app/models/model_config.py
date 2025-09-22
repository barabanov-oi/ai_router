"""Настройки моделей LLM."""

from datetime import datetime

from . import db


# NOTE[agent]: Модель описывает возможные конфигурации моделей у разных провайдеров.
class ModelConfig(db.Model):
    """Хранит параметры модели LLM для переключения в админке."""

    __tablename__ = "model_configs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    model = db.Column(db.String(128), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey("llm_providers.id"), nullable=False)
    temperature = db.Column(db.Float, default=1.0, nullable=False)
    max_tokens = db.Column(db.Integer, default=512, nullable=False)
    top_p = db.Column(db.Float, default=1.0, nullable=False)
    frequency_penalty = db.Column(db.Float, default=0.0, nullable=False)
    presence_penalty = db.Column(db.Float, default=0.0, nullable=False)
    system_instruction = db.Column(db.Text, nullable=True)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    dialog_token_limit = db.Column(db.Integer, default=20000, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    provider = db.relationship("LLMProvider", back_populates="models")

    # NOTE[agent]: Метод возвращает словарь параметров для OpenAI API.
    def to_request_options(self) -> dict:
        """Формирует базовый набор параметров для обращения к LLM."""

        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
        }

    # NOTE[agent]: Метод сохранён для обратной совместимости с существующим кодом.
    def to_openai_kwargs(self) -> dict:
        """Возвращает параметры модели для OpenAI (синоним to_request_options)."""

        return self.to_request_options()

    def __repr__(self) -> str:
        """Возвращает строковое представление конфигурации модели."""

        provider_part = f" provider={self.provider_id}" if self.provider_id else ""
        return f"<ModelConfig id={self.id} name={self.name}{provider_part} default={self.is_default}>"
