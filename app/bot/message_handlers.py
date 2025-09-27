"""Миксин с обработчиками команд и сообщений Telegram-бота."""

from __future__ import annotations

import threading
from html import escape as html_escape

from typing import Any, List, Optional


ERROR_USER_MESSAGE = "Произошла ошибка.\n<i>Наша команда уже работает над её устранением.</i>"
DEFAULT_PAUSE_MESSAGE = "Бот временно недоступен. Пожалуйста, попробуйте позже."

from telebot import TeleBot, types

from ..models import BotCommand, Dialog, MessageLog, db


class MessageHandlingMixin:
    """Регистрирует обработчики и реализует реакции на события бота."""

    # NOTE[agent]: Создание экземпляра TeleBot и регистрация обработчиков.
    def _create_bot(self, token: str) -> TeleBot:
        """Создаёт экземпляр TeleBot и регистрирует обработчики."""

        bot = TeleBot(token, parse_mode="HTML")

        with self._app_context():
            custom_commands = list(BotCommand.query.all())

        custom_command_mapping: dict[str, str] = {}
        for command in custom_commands:
            command_name = (command.name or "").lstrip("/").lower()
            if not command_name:
                continue
            custom_command_mapping[command_name] = command.response_text

        known_commands = {"start", "help", *custom_command_mapping.keys()}

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

    # NOTE[agent]: Проверяет, активирован ли режим приостановки бота.
    def _is_bot_paused(self) -> bool:
        """Сообщает, включён ли режим приостановки работы бота."""

        raw_value = (self._settings.get("bot_paused", "0") or "").strip().lower()
        return raw_value in {"1", "true", "yes", "on"}

    # NOTE[agent]: Возвращает текст ответа для режима приостановки.
    def _get_pause_message(self) -> str:
        """Извлекает текст, отправляемый при приостановке бота."""

        message = (self._settings.get("bot_pause_message", "") or "").strip()
        return message or DEFAULT_PAUSE_MESSAGE

    # NOTE[agent]: Отправляет сообщение о приостановке пользователю и прекращает обработку.
    def _respond_if_paused(self, chat_id: int) -> bool:
        """Отправляет уведомление, если бот находится в режиме паузы."""

        if not self._is_bot_paused():
            return False
        self._send_message(
            chat_id=chat_id,
            text=self._get_pause_message(),
            parse_mode="HTML",
            escape=False,
        )
        return True

    # NOTE[agent]: Обрабатывает паузу для callback-запросов.
    def _respond_if_paused_callback(self, call: types.CallbackQuery) -> bool:
        """Оповещает пользователя о паузе и завершает обработку callback."""

        if not self._is_bot_paused():
            return False
        if self._bot:
            try:
                self._bot.answer_callback_query(call.id, text="Работа бота приостановлена")
            except Exception:  # pylint: disable=broad-except
                self._get_logger().debug("Не удалось ответить на callback при паузе", exc_info=True)
        chat_id = call.message.chat.id if call.message else call.from_user.id
        self._send_message(
            chat_id=chat_id,
            text=self._get_pause_message(),
            parse_mode="HTML",
            escape=False,
        )
        return True

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

    # NOTE[agent]: Приветственное сообщение и первичная регистрация пользователя.
    def _handle_start(self, message: types.Message) -> None:
        """Отправляет приветствие и регистрирует пользователя."""

        user = self._get_or_create_user(message.from_user)
        if self._respond_if_paused(message.chat.id):
            return
        text = (
            "👋 <b>Привет!</b>\n\n"
            "Я — бот для общения с нейросетью GPT.\n\n"
            "Просто напишите свой вопрос, задачу или идею — и получите ответ прямо здесь, в чате.\n\n"
            "📌 Попробуйте начать с простого:\n"
            "«Составь список дел на завтра»\n"
            "или\n"
            "«Объясни разницу между SEO и контекстной рекламой простыми словами».\n\n"
            "✨ Чем точнее запрос, тем полезнее будет ответ.\n\n"
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
            "<b>Хороший ответ начинается с чёткого вопроса.</b>\n"
            "Если задача размыта, ответ получится общим. Сформулируйте: что именно нужно, в каком контексте и для какой цели. Чем яснее вопрос — тем точнее результат.\n\n"
            "<b>Ставьте знак препинания в конце.</b>\n"
            "Иначе бот может продолжить вашу фразу вместо ответа.\n\n"
            "<b>Уточняйте объём и формат.</b>\n"
            "Например: 200 слов, 500 символов, 3 предложения. Формат — список, инструкция, письмо, код.\n\n"
            "<b>Добавляйте детали.</b>\n"
            "❌ «Расскажи про цветы»\n"
            "✅ «Составь список из 5 самых популярных комнатных растений с кратким описанием ухода».\n\n"
            "<b>Формулируйте запрос одним сообщением.</b>\n"
            "Бот не собирает несколько кусочков в единую задачу.\n\n"
            "✨ Для сложных тем можно попросить уточняющие вопросы после описания задачи: «Задай мне уточняющие вопросы, чтобы я получил максимально точный ответ»."
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

    def _is_unknown_command(self, message: types.Message, known_commands: set[str]) -> bool:
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

    # NOTE[agent]: Формирует предупреждение о превышении лимита токенов.
    def _build_dialog_limit_message(self, limit: int, total: int) -> str:
        """Возвращает текст уведомления о достигнутом лимите токенов.

        Args:
            limit: Установленный лимит токенов для диалога.
            total: Фактическое количество израсходованных токенов.

        Returns:
            Строку с предупреждением и рекомендацией начать новый диалог.
        """

        limit_value = f"{limit:,}".replace(",", " ")
        total_value = f"{total:,}".replace(",", " ")
        return (
            "⚠️ <b>Лимит токенов для диалога исчерпан.</b>\n"
            f"Использовано {total_value} токенов при лимите {limit_value}.\n"
            "Начните новый диалог или выберите ранее сохранённый в истории."
        )

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
                if self._bot:
                    self._clear_previous_reply_markup(dialog, message.chat.id)
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
                chunks = self._prepare_response_chunks(response_text or "")
                last_message_id: Optional[int] = None
                for index, chunk in enumerate(chunks):
                    markup = None
                    is_last_chunk = index == len(chunks) - 1
                    if is_last_chunk and not usage_summary and not limit_exceeded:
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
                if usage_summary:
                    summary_markup = None if limit_exceeded else reply_markup
                    sent = self._send_message(
                        chat_id=message.chat.id,
                        text=usage_summary,
                        parse_mode="HTML",
                        reply_markup=summary_markup,
                        escape=False,
                    )
                    if summary_markup is not None:
                        last_message_id = getattr(sent, "message_id", None)
                if limit_exceeded and warning_text:
                    sent = self._send_message(
                        chat_id=message.chat.id,
                        text=warning_text,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                        escape=False,
                    )
                    last_message_id = getattr(sent, "message_id", None)
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
