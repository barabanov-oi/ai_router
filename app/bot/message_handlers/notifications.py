"""Рассылка уведомлений об ошибках Telegram-бота."""

from __future__ import annotations

from html import escape as html_escape
from typing import List, Optional

from telebot import types


class ErrorNotificationMixin:
    """Инкапсулирует логику уведомлений об ошибках."""

    # NOTE[agent]: Возвращает список получателей уведомлений об ошибках.
    def _get_error_notification_recipients(self) -> List[int]:
        """Собирает идентификаторы чатов для отправки уведомлений об ошибках."""

        raw_value = (self._settings.get("error_notification_user_ids", "") or "").replace(",", " ")
        normalized = raw_value.replace(";", " ").replace("\n", " ").replace("\t", " ")
        recipients: List[int] = []
        for token in normalized.split():
            try:
                recipients.append(int(token))
            except ValueError:
                self._get_logger().debug("Пропущен некорректный user_id для уведомлений: %s", token)
        return recipients

    # NOTE[agent]: Отправляет уведомление администраторам о критической ошибке.
    def _notify_error_subscribers(
        self,
        *,
        message: Optional[types.Message],
        exception: Exception,
    ) -> None:
        """Рассылает административное уведомление о падении обработки сообщения."""

        if not self._bot:
            return
        recipients = self._get_error_notification_recipients()
        if not recipients:
            return
        unique_recipients = []
        seen: set[int] = set()
        for recipient in recipients:
            if recipient in seen:
                continue
            seen.add(recipient)
            unique_recipients.append(recipient)
        user_id: Optional[int] = None
        username: Optional[str] = None
        chat_id: Optional[int] = None
        message_text: Optional[str] = None
        if message:
            if message.from_user:
                user_id = message.from_user.id
                username = message.from_user.username
            if message.chat:
                chat_id = message.chat.id
            message_text = message.text
        user_parts: List[str] = []
        if user_id is not None:
            user_parts.append(f"ID: <code>{user_id}</code>")
        if username:
            user_parts.append(f"@{html_escape(username)}")
        if chat_id is not None and chat_id != user_id:
            user_parts.append(f"chat: <code>{chat_id}</code>")
        description_lines = ["⚠️ <b>Ошибка при обработке сообщения</b>"]
        if user_parts:
            description_lines.append("Пользователь — " + ", ".join(user_parts))
        if message_text:
            description_lines.append(f"Запрос:\n<pre>{html_escape(message_text)}</pre>")
        description_lines.append(f"Ошибка: <code>{html_escape(str(exception))}</code>")
        notification_text = "\n".join(description_lines)
        for recipient in unique_recipients:
            if chat_id is not None and recipient == chat_id:
                continue
            try:
                self._bot.send_message(
                    chat_id=recipient,
                    text=notification_text,
                    parse_mode="HTML",
                )
            except Exception:  # pylint: disable=broad-except
                self._get_logger().exception(
                    "Не удалось отправить уведомление об ошибке получателю %s",
                    recipient,
                )
