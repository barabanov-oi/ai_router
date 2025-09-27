"""Обработчики управления диалогами Telegram-бота."""

from __future__ import annotations

from html import escape as html_escape
from typing import Optional

from telebot import types

from ...models import Dialog, MessageLog, db


class DialogHistoryHandlersMixin:
    """Содержит обработчики истории и переключения диалогов."""

    # NOTE[agent]: Удаление inline-клавиатуры у предыдущих ответов LLM.
    def _clear_previous_reply_markup(self, dialog: Dialog, chat_id: int) -> None:
        """Отключает клавиатуру у всех ранее отправленных ответов ассистента."""

        if not self._bot:
            return
        previous_responses = (
            MessageLog.query.filter(
                MessageLog.dialog_id == dialog.id,
                MessageLog.assistant_message_id.isnot(None),
            )
            .order_by(MessageLog.message_index.asc())
            .all()
        )
        for log_entry in previous_responses:
            if not log_entry.assistant_message_id:
                continue
            try:
                self._bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=log_entry.assistant_message_id,
                    reply_markup=None,
                )
            except Exception:  # pylint: disable=broad-except
                self._get_logger().debug(
                    "Не удалось удалить клавиатуру у сообщения %s",
                    log_entry.assistant_message_id,
                    exc_info=True,
                )

    # NOTE[agent]: Удаляет inline-клавиатуру у сообщения, по которому пришёл callback.
    def _remove_message_reply_markup(self, message: Optional[types.Message]) -> None:
        """Скрывает клавиатуру у указанного сообщения, если оно ещё доступно."""

        if not self._bot or not message:
            return
        try:
            self._bot.edit_message_reply_markup(
                chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=None,
            )
        except Exception:  # pylint: disable=broad-except
            self._get_logger().debug(
                "Не удалось снять клавиатуру с сообщения %s",
                message.message_id,
                exc_info=True,
            )

    # NOTE[agent]: Безопасно удаляет сообщение с клавиатурой истории.
    def _delete_message_safely(self, message: Optional[types.Message]) -> None:
        """Удаляет сообщение бота, игнорируя ошибки Telegram API."""

        if not self._bot or not message:
            return
        try:
            self._bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception:  # pylint: disable=broad-except
            self._get_logger().debug(
                "Не удалось удалить сообщение %s",
                message.message_id,
                exc_info=True,
            )

    # NOTE[agent]: Завершение текущего диалога и создание нового.
    def _handle_new_dialog(self, call: types.CallbackQuery) -> None:
        """Создаёт новый диалог для пользователя."""

        if self._respond_if_paused_callback(call):
            return
        user = self._get_or_create_user(call.from_user)
        self._remove_message_reply_markup(call.message)
        current_dialog = self._get_active_dialog(user)
        if current_dialog:
            current_dialog.close()
        new_dialog = Dialog(
            user_id=user.id,
            title="✨ Новый диалог",
            telegram_chat_id=str(call.message.chat.id),
        )
        db.session.add(new_dialog)
        db.session.commit()
        if self._bot:
            self._bot.answer_callback_query(call.id, text="✨ Создан новый диалог")
        self._send_message(
            chat_id=call.message.chat.id,
            text="🧹 Контекст очищен. Продолжайте беседу.",
            parse_mode="HTML",
            reply_markup=self._build_inline_keyboard(),
        )

    # NOTE[agent]: Обработчик вызова истории диалогов.
    def _handle_dialog_history(self, call: types.CallbackQuery) -> None:
        """Отправляет пользователю клавиатуру с историей диалогов."""

        if self._respond_if_paused_callback(call):
            return
        user = self._get_or_create_user(call.from_user)
        if not self._bot:
            return
        self._remove_message_reply_markup(call.message)
        dialogs = self._get_recent_dialogs(user)
        if not dialogs:
            self._bot.answer_callback_query(call.id, text="История пуста")
            return
        history_keyboard = self._build_history_keyboard(user)
        self._bot.answer_callback_query(call.id)
        self._send_message(
            chat_id=call.message.chat.id,
            text="Выберите диалог из истории:",
            parse_mode="HTML",
            reply_markup=history_keyboard,
        )

    # NOTE[agent]: Обработчик переключения активного диалога.
    def _handle_switch_dialog(self, call: types.CallbackQuery) -> None:
        """Переключает пользователя на выбранный диалог из истории."""

        if self._respond_if_paused_callback(call):
            return
        if not self._bot:
            return
        self._bot.answer_callback_query(call.id)
        user = self._get_or_create_user(call.from_user)
        dialog_id = self._extract_dialog_id(call.data)
        if dialog_id is None:
            self._send_message(
                chat_id=call.message.chat.id,
                text="Не удалось определить диалог",
                parse_mode="HTML",
            )
            return
        target_dialog = Dialog.query.filter_by(id=dialog_id, user_id=user.id).first()
        if not target_dialog:
            self._send_message(
                chat_id=call.message.chat.id,
                text="Диалог не найден",
                parse_mode="HTML",
            )
            return
        if not target_dialog.telegram_chat_id:
            target_dialog.telegram_chat_id = str(call.message.chat.id)
        self._activate_dialog(user, target_dialog)
        history_message = call.message
        chat_id: int | None = None
        if history_message:
            chat_id = history_message.chat.id
        elif target_dialog.telegram_chat_id:
            try:
                chat_id = int(target_dialog.telegram_chat_id)
            except (TypeError, ValueError):
                chat_id = None
        if chat_id is None:
            chat_id = call.from_user.id
        self._delete_message_safely(history_message)
        reply_message_id, last_text = self._get_last_message_reference(target_dialog)
        title = self._format_dialog_title(target_dialog)
        base_text = f"🔄 Переключаюсь на диалог <b>«{html_escape(title)}»</b>."
        reply_markup = self._build_inline_keyboard()
        if reply_message_id is not None:
            self._send_message(
                chat_id=chat_id,
                text=base_text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                reply_to_message_id=reply_message_id,
                escape=False,
            )
            return
        snippet = last_text or ""
        if snippet:
            escaped_lines = [
                f"&gt; {html_escape(line)}" if line else "&gt;"
                for line in snippet.splitlines()
            ] or ["&gt;"]
            quoted_snippet = "\n".join(escaped_lines)
            message_text = (
                f"{base_text}\n"
                "📩 Последнее сообщение:\n"
                f"<pre>{quoted_snippet}</pre>"
            )
        else:
            message_text = (
                f"{base_text}\n"
                "🚫 Последнее сообщение не найдено."
            )
        self._send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            escape=False,
        )

    def _extract_dialog_id(self, payload: Optional[str]) -> Optional[int]:
        """Извлекает идентификатор диалога из callback-данных."""

        if not payload:
            return None
        parts = payload.split(":")
        if len(parts) != 3:
            return None
        try:
            return int(parts[-1])
        except ValueError:
            return None
