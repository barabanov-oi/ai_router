"""Обработка входящих сообщений и отправка ответов."""

from __future__ import annotations

import threading
from html import escape as html_escape
from typing import Any, List, Optional

from telebot import types

from ...models import Dialog, MessageLog, db

ERROR_USER_MESSAGE = "Произошла ошибка.\n<i>Наша команда уже работает над её устранением.</i>"


class MessagingMixin:
    """Инкапсулирует обработку текстовых сообщений и отправку ответов."""

    # NOTE[agent]: Основная обработка текстового сообщения.
    def _handle_message(self, message: types.Message) -> None:
        """Обрабатывает входящее текстовое сообщение и запрашивает ответ LLM."""

        user = self._get_or_create_user(message.from_user)
        if self._respond_if_paused(message.chat.id):
            return
        if not user.is_active:
            if self._bot:
                self._send_message(
                    chat_id=message.chat.id,
                    text="Ваш доступ к боту ограничен. Обратитесь к администратору.",
                    parse_mode="HTML",
                )
            return

        dialog = self._get_active_dialog(user)
        if not dialog:
            dialog = Dialog(
                user_id=user.id,
                title="Диалог",
                telegram_chat_id=str(message.chat.id),
            )
            db.session.add(dialog)
            db.session.commit()
        elif not dialog.telegram_chat_id:
            dialog.telegram_chat_id = str(message.chat.id)

        message_index = MessageLog.query.filter_by(dialog_id=dialog.id).count() + 1
        log_entry = MessageLog(
            dialog_id=dialog.id,
            user_id=user.id,
            message_index=message_index,
            user_message=message.text,
            mode=user.preferred_mode,
            user_message_id=message.message_id,
        )
        db.session.add(log_entry)
        user.touch()
        if message_index == 1 and message.text:
            dialog.title = " ".join(message.text.split())[:255]
        db.session.commit()

        typing_stop_event: threading.Event | None = None
        typing_thread: threading.Thread | None = None

        limit_before = self._determine_effective_dialog_limit(dialog=dialog)
        if limit_before is not None:
            _, _, total_before = self._calculate_dialog_usage(dialog)
            if total_before >= limit_before:
                warning_text = self._build_dialog_limit_message(limit_before, total_before)
                reply_markup = self._build_inline_keyboard()
                sent_warning = self._send_message(
                    chat_id=message.chat.id,
                    text=warning_text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    escape=False,
                )
                log_entry.llm_response = warning_text
                if sent_warning is not None:
                    log_entry.assistant_message_id = getattr(sent_warning, "message_id", None)
                db.session.commit()
                return

        if self._bot:
            self._bot.send_chat_action(message.chat.id, "typing")

            typing_stop_event = threading.Event()

            def _keep_typing_indicator() -> None:
                """Периодически отправляет действие "typing", пока запрос выполняется."""

                # NOTE[agent]: Фоновая задача поддерживает индикацию набора текста.
                while not typing_stop_event.wait(4.0):
                    try:
                        if not self._bot:
                            break
                        self._bot.send_chat_action(message.chat.id, "typing")
                    except Exception:  # pylint: disable=broad-except
                        self._get_logger().debug(
                            "Не удалось обновить индикацию набора текста", exc_info=True
                        )
                        break

            typing_thread = threading.Thread(
                target=_keep_typing_indicator,
                name="telegram-typing-indicator",
                daemon=True,
            )
            typing_thread.start()
        try:
            response_text = self._query_llm(dialog, log_entry)
            db.session.refresh(log_entry)
            usage_summary, total_tokens, limit_value = self._format_usage_summary(dialog, log_entry)
            reply_markup = self._build_inline_keyboard()
            limit_exceeded = limit_value is not None and total_tokens >= limit_value
            warning_text: Optional[str] = None
            if limit_exceeded and limit_value is not None:
                warning_text = self._build_dialog_limit_message(limit_value, total_tokens)
            if self._bot:
                self._clear_previous_reply_markup(dialog, message.chat.id)
                combined_text = response_text or ""
                if usage_summary:
                    combined_text = (
                        f"{combined_text}\n\n{usage_summary}" if combined_text else usage_summary
                    )
                chunks = self._prepare_response_chunks(combined_text)
                last_message_id: Optional[int] = None
                for index, chunk in enumerate(chunks):
                    markup = None
                    is_last_chunk = index == len(chunks) - 1
                    if is_last_chunk and not limit_exceeded:
                        markup = reply_markup
                    sent = self._send_message(
                        chat_id=message.chat.id,
                        text=chunk,
                        parse_mode="Markdown",
                        reply_markup=markup,
                        escape=False,
                    )
                    if markup is not None:
                        last_message_id = getattr(sent, "message_id", None)
                if limit_exceeded and warning_text:
                    self._send_message(
                        chat_id=message.chat.id,
                        text=warning_text,
                        parse_mode="HTML",
                        reply_markup=None,
                        escape=False,
                    )
                if last_message_id is not None:
                    log_entry.assistant_message_id = last_message_id
                    db.session.commit()
        except Exception as exc:  # pylint: disable=broad-except
            self._get_logger().exception("Ошибка при обращении к LLM")
            if self._bot:
                self._send_message(
                    chat_id=message.chat.id,
                    text=ERROR_USER_MESSAGE,
                    parse_mode="HTML",
                    reply_markup=self._build_inline_keyboard(),
                    escape=False,
                )
            self._notify_error_subscribers(message=message, exception=exc)
        finally:
            if typing_stop_event:
                typing_stop_event.set()
            if typing_thread:
                typing_thread.join(timeout=2.0)

    # NOTE[agent]: Разбивает ответ ассистента на части для обхода лимитов Telegram.
    def _prepare_response_chunks(self, text: str, *, escape: bool = False) -> List[str]:
        """Делит ответ LLM на части с учётом ограничений Telegram."""

        if not text:
            return []
        processed_text = self._escape_html(text) if escape else text
        continuation = "..."
        if len(processed_text) <= 4096:
            return [processed_text]

        chunks: List[str] = []
        remaining = processed_text
        first_chunk = True

        while remaining:
            if first_chunk:
                needs_split = len(remaining) > 4096
                suffix = continuation if needs_split else ""
                available = 4096 - len(suffix)
                prefix = ""
            else:
                needs_split = len(remaining) > (4096 - len(continuation))
                prefix = continuation
                suffix = continuation if needs_split else ""
                available = 4096 - len(prefix) - len(suffix)

            if available <= 0:
                available = 4096
                prefix = ""
                suffix = ""

            if len(remaining) <= available:
                core = remaining
                remaining = ""
            else:
                core = remaining[:available]
                split_pos = core.rfind(" ")
                if split_pos <= 0:
                    split_pos = available
                core = core[:split_pos].rstrip()
                remaining = remaining[split_pos:].lstrip()

            chunk = f"{prefix}{core}{suffix}"
            chunks.append(chunk)
            first_chunk = False

            if not remaining:
                break

        return chunks

    # NOTE[agent]: Формирует предупреждение о превышении лимта токенов.
    def _build_dialog_limit_message(self, limit: int, total: int) -> str:
        """Возвращает текст уведомления о достигнутом лимите токенов."""

        limit_value = self._format_tokens_number(limit)
        total_value = self._format_tokens_number(total)
        return (
            "⚠️ <b>Лимит токенов для диалога исчерпан.</b>\n"
            f"Использовано {total_value} токенов при лимите {limit_value}.\n"
            "Начните новый диалог или выберите ранее сохранённый в истории."
        )

    # NOTE[agent]: Централизованное экранирование текста под HTML.
    def _escape_html(self, text: str | None) -> str:
        """Возвращает текст с экранированными спецсимволами HTML."""

        if not text:
            return ""
        return html_escape(text)

    # NOTE[agent]: Унифицированная отправка сообщений с автоматическим экранированием.
    def _send_message(
        self,
        *,
        chat_id: int,
        text: str,
        parse_mode: str | None = "HTML",
        escape: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Отправляет сообщение через бота с учётом экранирования HTML."""

        if not self._bot:
            return None
        safe_text = text
        final_parse_mode = parse_mode or "HTML"
        if escape and final_parse_mode == "HTML":
            safe_text = self._escape_html(text)
        return self._bot.send_message(
            chat_id=chat_id,
            text=safe_text,
            parse_mode=final_parse_mode,
            **kwargs,
        )
