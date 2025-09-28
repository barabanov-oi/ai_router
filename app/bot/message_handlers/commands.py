"""Регистрация команд и обработчиков Telegram-бота."""

from __future__ import annotations

from typing import Dict, Set

from telebot import TeleBot, types

from ...models import BotCommand


class CommandHandlersMixin:
    """Создаёт экземпляр бота и регистрирует обработчики команд."""

    # NOTE[agent]: Создание экземпляра TeleBot и регистрация обработчиков.
    def _create_bot(self, token: str) -> TeleBot:
        """Создаёт экземпляр TeleBot и регистрирует обработчики."""

        bot = TeleBot(token, parse_mode="HTML")

        with self._app_context():
            custom_commands = list(BotCommand.query.all())

        custom_command_mapping: Dict[str, str] = {}
        for command in custom_commands:
            command_name = (command.name or "").lstrip("/").lower()
            if not command_name:
                continue
            custom_command_mapping[command_name] = command.response_text

        known_commands: Set[str] = {"start", "help", *custom_command_mapping.keys()}

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

        for command_name, response_text in custom_command_mapping.items():

            @bot.message_handler(commands=[command_name])
            def handle_custom_command(
                message: types.Message,
                prepared_response: str = response_text,
            ) -> None:
                """Отправляет ответ, сохранённый для пользовательской команды."""

                with self._app_context():
                    if self._respond_if_paused(message.chat.id):
                        return
                    self._send_message(
                        chat_id=message.chat.id,
                        text=prepared_response,
                        parse_mode="HTML",
                        escape=False,
                    )

        @bot.message_handler(
            func=lambda message, commands=known_commands: self._is_unknown_command(message, commands)
        )
        def handle_unknown_command(message: types.Message) -> None:
            """Обрабатывает неизвестные команды."""

            with self._app_context():
                self._handle_unknown_command(message)

        @bot.callback_query_handler(func=lambda call: call.data == "dialog:new")
        def handle_new_dialog(call: types.CallbackQuery) -> None:
            """Сбрасывает текущий контекст диалога."""

            with self._app_context():
                self._handle_new_dialog(call)

        @bot.callback_query_handler(func=lambda call: call.data == "dialog:history")
        def handle_dialog_history(call: types.CallbackQuery) -> None:
            """Отображает список последних диалогов пользователя."""

            with self._app_context():
                self._handle_dialog_history(call)

        @bot.callback_query_handler(func=lambda call: call.data.startswith("dialog:switch:"))
        def handle_dialog_switch(call: types.CallbackQuery) -> None:
            """Переключает активный диалог пользователя."""

            with self._app_context():
                self._handle_switch_dialog(call)

        @bot.message_handler(
            content_types=["text"],
            func=lambda message: self._extract_command(message.text or "") is None,
        )
        def handle_text(message: types.Message) -> None:
            """Обрабатывает текстовые сообщения пользователей."""

            with self._app_context():
                self._handle_message(message)

        return bot

    # NOTE[agent]: Приветственное сообщение и первичная регистрация пользователя.
    def _handle_start(self, message: types.Message) -> None:
        """Отправляет приветствие и регистрирует пользователя."""

        user = self._get_or_create_user(message.from_user)
        if self._respond_if_paused(message.chat.id):
            return
        text = (
            "👋 <b>Привет!</b>\n\n"
            "Я — бот для общения с нейросетью.\n\n"
            "<i>Просто напишите свой вопрос, задачу или идею — и получите ответ прямо здесь, в чате.</i>\n\n"
            "📌 Попробуй начать с простого:\n"
            "«<code>Составь список дел на завтра</code>»\n\n"
            "или\n\n"
            "«<code>Объясни разницу между SEO и контекстной рекламой простыми словами</code>».\n\n"
            "✨ <i>Чем точнее запрос, тем полезнее будет ответ.</i>\n\n"
            "Подробнее о том, как составить запрос можно узнать в разделе /help"
        )
        self._send_message(
            chat_id=message.chat.id,
            text=text,
            parse_mode="HTML",
            escape=False,
            reply_markup=self._build_inline_keyboard(),
        )
        self._get_logger().info("Пользователь %s (%s) начал работу", user.telegram_id, user.username)

    # NOTE[agent]: Подробная справка по возможностям бота.
    def _handle_help(self, message: types.Message) -> None:
        """Отправляет инструкции по использованию бота."""

        if self._respond_if_paused(message.chat.id):
            return
        help_text = (
            "✍️ <b>Как задавать запросы</b>\n\n"
            "— Формулируйте чётко: тема + цель.\n"
            "— Ставьте знак препинания в конце.\n"
            "— Указывайте формат ответа (краткий/полный/структурированный и т.п.).\n"
            "— Добавляйте детали\n\n"
            "❌ «<code>Расскажи про цветы</code>»\n"
            "✅ «<code>Составь список из 5 популярных комнатных растений с описанием ухода</code>».\n\n"
            "— Пишите запрос одним сообщением.\n"
            "— Для сложных тем можно попросить уточняющие вопросы после описания задачи: «Задай мне уточняющие вопросы, чтобы я получил максимально точный ответ».\n\n"
            "💬 <b>Диалоги</b>\n\n"
            "— Бот «помнит» историю переписки.\n"
            "— Можно уточнять и задавать вопросы в рамках диалога.\n"
            "— Для новой задачи начните новый диалог.\n\n"
            "🗂 <b>Контекстное окно</b>\n\n"
            "— Это объём текста, который бот «помнит» и он измеряется в токенах.\n"
            "— Объём диалога ограничен токенами.\n"
            "— Информация о токенах выводится в конце каждого ответа нейросети\n"

        )
        self._send_message(
            chat_id=message.chat.id,
            text=help_text,
            parse_mode="HTML",
            escape=False,
            reply_markup=self._build_inline_keyboard(),
        )

    def _extract_command(self, text: str) -> str | None:
        """Возвращает имя команды, если сообщение начинается со знака '/'."""

        if not text or not text.startswith("/"):
            return None
        command = text.split()[0][1:]
        if "@" in command:
            command = command.split("@", 1)[0]
        return command.lower()

    def _is_unknown_command(self, message: types.Message, known_commands: Set[str]) -> bool:
        """Определяет, относится ли сообщение к неизвестной команде."""

        command = self._extract_command(message.text or "")
        return command is not None and command not in known_commands

    def _handle_unknown_command(self, message: types.Message) -> None:
        """Отправляет уведомление об отсутствующей команде."""

        if self._respond_if_paused(message.chat.id):
            return
        self._send_message(
            chat_id=message.chat.id,
            text="Команда не найдена.",
            parse_mode="HTML",
        )
