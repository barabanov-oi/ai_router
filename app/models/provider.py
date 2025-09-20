"""Поставщики API для LLM."""

from datetime import datetime
from typing import Dict, Optional, Tuple

from . import db


# NOTE[agent]: Модель описывает источник API-ключа для обращений к LLM.
class LLMProvider(db.Model):
    """Хранит данные поставщиков LLM и их API-ключи."""

    __tablename__ = "llm_providers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    vendor = db.Column(db.String(64), nullable=False)
    api_key = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    models = db.relationship(
        "ModelConfig",
        back_populates="provider",
        cascade="all, delete-orphan",
    )

    VENDOR_OPENAI = "openai"
    VENDOR_GOOGLE = "google"
    VENDOR_GROQ = "groq"

    # NOTE[agent]: Метод предоставляет перечень допустимых поставщиков.
    @classmethod
    def allowed_vendors(cls) -> Tuple[str, ...]:
        """Возвращает поддерживаемых поставщиков API."""

        return (cls.VENDOR_OPENAI, cls.VENDOR_GOOGLE, cls.VENDOR_GROQ)

    # NOTE[agent]: Метод сопоставляет внутренние идентификаторы и отображаемые названия.
    @classmethod
    def vendor_titles(cls) -> Dict[str, str]:
        """Возвращает словарь для отображения названий поставщиков."""

        return {
            cls.VENDOR_OPENAI: "OpenAI",
            cls.VENDOR_GOOGLE: "Google",
            cls.VENDOR_GROQ: "Groq",
        }

    # NOTE[agent]: Метод обновляет данные поставщика и сбрасывает кэш клиентов.
    def update_credentials(
        self,
        *,
        name: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        """Обновляет имя и API-ключ поставщика."""

        if name is not None:
            self.name = name
        if api_key is not None:
            self.api_key = api_key
        self.updated_at = datetime.utcnow()

    @property
    def display_vendor(self) -> str:
        """Возвращает удобочитаемое название поставщика."""

        return self.vendor_titles().get(self.vendor, self.vendor)

    def __repr__(self) -> str:
        """Возвращает строковое представление поставщика."""

        return f"<LLMProvider id={self.id} vendor={self.vendor}>"
