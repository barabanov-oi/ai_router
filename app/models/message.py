"""ORM-модель для логирования сообщений."""

from datetime import datetime

from . import db


# NOTE[agent]: Модель хранит пары запрос/ответ для аналитики и восстановления контекста.
class MessageLog(db.Model):
    """Логи запросов пользователей и ответов модели."""

    __tablename__ = "message_logs"

    id = db.Column(db.Integer, primary_key=True)
    dialog_id = db.Column(db.Integer, db.ForeignKey("dialogs.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message_index = db.Column(db.Integer, nullable=False)
    user_message = db.Column(db.Text, nullable=False)
    llm_response = db.Column(db.Text, nullable=True)
    mode = db.Column(db.String(64), default="default", nullable=False)
    model_id = db.Column(db.Integer, db.ForeignKey("model_configs.id"), nullable=True)
    tokens_used = db.Column(db.Integer, default=0, nullable=False)
    prompt_tokens = db.Column(db.Integer, default=0, nullable=False)
    completion_tokens = db.Column(db.Integer, default=0, nullable=False)
    user_message_id = db.Column(db.BigInteger, nullable=True)
    assistant_message_id = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    responded_at = db.Column(db.DateTime, nullable=True)

    model = db.relationship("ModelConfig")

    # NOTE[agent]: Метод обновляет данные о полученном ответе от LLM.
    def register_response(
        self,
        response_text: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Сохраняет ответ LLM и статистику расхода токенов.

        Args:
            response_text: Текст ответа модели.
            prompt_tokens: Количество токенов вопроса (input).
            completion_tokens: Количество токенов ответа (output).
        """

        safe_prompt = max(int(prompt_tokens or 0), 0)
        safe_completion = max(int(completion_tokens or 0), 0)
        self.llm_response = response_text
        self.prompt_tokens = safe_prompt
        self.completion_tokens = safe_completion
        self.tokens_used = safe_prompt + safe_completion
        self.responded_at = datetime.utcnow()

    def __repr__(self) -> str:
        """Возвращает строковое представление записи лога."""

        return f"<MessageLog id={self.id} dialog_id={self.dialog_id} index={self.message_index}>"
