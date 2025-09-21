"""Миксин с обработчиками команд и сообщений Telegram-бота."""

from __future__ import annotations

from typing import List

from telebot import TeleBot, types

from ..models import Dialog, MessageLog, db


class MessageHandlingMixin:
    """Регистрирует обработчики и реализует реакции на события бота."""

    # NOTE[agent]: Создание экземпляра TeleBot и регистрация обработчиков.
    def _create_bot(self, token: str) -> TeleBot:
        """Создаёт экземпляр TeleBot и регистрирует обработчики."""

        bot = TeleBot(token, parse_mode="HTML")

        @bot.message_handler(commands=["start"])
        def handle_start(message: types.Message) -> None:
            """Обрабатывает команду /start."""

            with self._app_context():
                self._handle_start(message)

        @bot.message_handler(commands=["help"])
        def handle_help(message: types.Message) -> None:
            """Обрабатывает команду /help."""

            with self._app_context():
                self._handle_help(message)

        @bot.callback_query_handler(func=lambda call: call.data == "dialog:new")
        def handle_new_dialog(call: types.CallbackQuery) -> None:
            """Сбрасывает текущий контекст диалога."""

            with self._app_context():
                self._handle_new_dialog(call)

        @bot.message_handler(content_types=["text"])
        def handle_text(message: types.Message) -> None:
            """Обрабатывает текстовые сообщения пользователей."""

            with self._app_context():
                self._handle_message(message)

        return bot

    # NOTE[agent]: Приветственное сообщение и первичная регистрация пользователя.
    def _handle_start(self, message: types.Message) -> None:
        """Отправляет приветствие и регистрирует пользователя."""

        user = self._get_or_create_user(message.from_user)
        text = (
            "Привет! Я помощник LLM. Задайте вопрос, и я постараюсь помочь.\n"
            "Используйте /help для справки."
        )
        if self._bot:
            self._bot.send_message(chat_id=message.chat.id, text=text)
        self._get_logger().info("Пользователь %s (%s) начал работу", user.telegram_id, user.username)

    # NOTE[agent]: Подробная справка по возможностям бота.
    def _handle_help(self, message: types.Message) -> None:
        """Отправляет инструкции по использованию бота."""

        help_text = (
            "Доступные команды:\n"
            "/start — начать работу\n"
            "/help — показать эту справку\n"
            "Кнопка 'Начать новый диалог' завершает текущий диалог и очищает контекст."
        )
        if self._bot:
            self._bot.send_message(chat_id=message.chat.id, text=help_text)

    # NOTE[agent]: Разбивает ответ ассистента на части для обхода лимитов Telegram.
    def _prepare_response_chunks(self, text: str) -> List[str]:
        """Делит ответ LLM на части с учётом ограничений Telegram."""

        if len(text) <= 4096:
            return [text]

        chunks: List[str] = []
        remaining = text
        continuation = "..."
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

    # NOTE[agent]: Завершение текущего диалога и создание нового.
    def _handle_new_dialog(self, call: types.CallbackQuery) -> None:
        """Создаёт новый диалог для пользователя."""

        user = self._get_or_create_user(call.from_user)
        current_dialog = self._get_active_dialog(user)
        if current_dialog:
            current_dialog.close()
        new_dialog = Dialog(user_id=user.id, title="Новый диалог")
        db.session.add(new_dialog)
        db.session.commit()
        if self._bot:
            self._bot.answer_callback_query(call.id, text="Создан новый диалог")
            self._bot.send_message(chat_id=call.message.chat.id, text="Контекст очищен. Продолжайте беседу.")

    # NOTE[agent]: Основная обработка текстового сообщения.
    def _handle_message(self, message: types.Message) -> None:
        """Обрабатывает входящее текстовое сообщение и запрашивает ответ LLM."""

        user = self._get_or_create_user(message.from_user)
        if not user.is_active:
            if self._bot:
                self._bot.send_message(
                    chat_id=message.chat.id,
                    text="Ваш доступ к боту ограничен. Обратитесь к администратору.",
                )
            return

        dialog = self._get_active_dialog(user)
        if not dialog:
            dialog = Dialog(user_id=user.id, title="Диалог")
            db.session.add(dialog)
            db.session.commit()

        message_index = MessageLog.query.filter_by(dialog_id=dialog.id).count() + 1
        log_entry = MessageLog(
            dialog_id=dialog.id,
            user_id=user.id,
            message_index=message_index,
            user_message=message.text,
            mode=user.preferred_mode,
        )
        db.session.add(log_entry)
        user.touch()
        db.session.commit()

        if self._bot:
            self._bot.send_chat_action(message.chat.id, "typing")
        try:
            response_text = self._query_llm(dialog, log_entry)
            reply_markup = self._build_inline_keyboard()
            if self._bot:
                chunks = self._prepare_response_chunks(response_text)
                for index, chunk in enumerate(chunks):
                    markup = reply_markup if index == len(chunks) - 1 else None
                    self._bot.send_message(chat_id=message.chat.id, text=chunk, reply_markup=markup)
        except Exception as exc:  # pylint: disable=broad-except
            self._get_logger().exception("Ошибка при обращении к LLM")
            if self._bot:
                self._bot.send_message(chat_id=message.chat.id, text=f"Произошла ошибка: {exc}")
