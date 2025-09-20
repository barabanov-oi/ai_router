"""Миксин с обработчиками команд и сообщений Telegram-бота."""

from __future__ import annotations

from telebot import TeleBot, types

from ..models import Dialog, MessageLog, db
from .bot_modes import MODE_DEFINITIONS


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

        @bot.message_handler(commands=["settings"])
        def handle_settings(message: types.Message) -> None:
            """Обрабатывает команду /settings."""

            with self._app_context():
                self._handle_settings(message)

        @bot.callback_query_handler(func=lambda call: call.data.startswith("mode:"))
        def handle_mode_change(call: types.CallbackQuery) -> None:
            """Реагирует на выбор режима ответа."""

            with self._app_context():
                self._handle_mode_change(call)

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
            "Используйте /help для справки и /settings для выбора режима."
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
            "/settings — выбрать режим ответов\n"
            "Кнопка 'Начать новый диалог' завершает текущий диалог и очищает контекст."
        )
        if self._bot:
            self._bot.send_message(chat_id=message.chat.id, text=help_text)

    # NOTE[agent]: Отображение настроек и inline-клавиатуры выбора режима.
    def _handle_settings(self, message: types.Message) -> None:
        """Показывает пользователю доступные режимы работы."""

        user = self._get_or_create_user(message.from_user)
        keyboard = types.InlineKeyboardMarkup()
        for mode_key, definition in MODE_DEFINITIONS.items():
            title = definition["title"]
            prefix = "✅ " if user.preferred_mode == mode_key else ""
            keyboard.add(types.InlineKeyboardButton(text=f"{prefix}{title}", callback_data=f"mode:{mode_key}"))
        if self._bot:
            self._bot.send_message(chat_id=message.chat.id, text="Выберите режим работы:", reply_markup=keyboard)

    # NOTE[agent]: Обработка выбора режима пользователем.
    def _handle_mode_change(self, call: types.CallbackQuery) -> None:
        """Сохраняет выбранный режим и уведомляет пользователя."""

        mode = call.data.split(":", maxsplit=1)[1]
        user = self._get_or_create_user(call.from_user)
        user.preferred_mode = mode if mode in MODE_DEFINITIONS else "default"
        db.session.commit()
        if self._bot:
            self._bot.answer_callback_query(call.id, text="Режим обновлён")
            self._bot.send_message(
                chat_id=call.message.chat.id,
                text=f"Новый режим: {MODE_DEFINITIONS[user.preferred_mode]['title']}",
            )

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
                self._bot.send_message(chat_id=message.chat.id, text=response_text, reply_markup=reply_markup)
        except Exception as exc:  # pylint: disable=broad-except
            self._get_logger().exception("Ошибка при обращении к LLM")
            if self._bot:
                self._bot.send_message(chat_id=message.chat.id, text=f"Произошла ошибка: {exc}")
