"""Telegram bot integration powered by pyTelegramBotAPI."""

from __future__ import annotations

import logging
from threading import Event, Thread
from typing import Optional

from flask import Flask

try:  # pragma: no cover - optional dependency
    from telebot import TeleBot, types
except ImportError:  # pragma: no cover - optional dependency
    TeleBot = None  # type: ignore
    types = None  # type: ignore

from app import register_bot_thread
from app.services import dialog_service, openai_service, settings_service, user_service

AVAILABLE_MODES = {
    "concise": "Краткий ответ",
    "detailed": "Развёрнутый ответ",
}

_bot: Optional[TeleBot] = None


# NOTE(agents): init_bot is called from the Flask application factory to start the polling thread.
def init_bot(app: Flask, stop_event: Event) -> Optional[TeleBot]:
    """Initialise the Telegram bot and start polling in a background thread."""

    global _bot
    if TeleBot is None:
        logging.warning("pyTelegramBotAPI is not installed; Telegram bot will not start")
        return None
    if _bot is not None:
        return _bot
    token = settings_service.get_setting("telegram_bot_token") or app.config.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logging.warning("Telegram bot token is not configured")
        return None
    _bot = TeleBot(token, parse_mode="HTML")
    _register_handlers(_bot, app)

    thread = Thread(target=_start_polling, args=(app, stop_event), daemon=True)
    register_bot_thread(thread)
    thread.start()
    logging.info("Telegram bot polling started")
    return _bot


# NOTE(agents): _start_polling wraps bot.infinity_polling with the Flask application context.
def _start_polling(app: Flask, stop_event: Event) -> None:
    """Run the bot polling loop until the provided stop event is set."""

    if TeleBot is None or _bot is None:
        return
    with app.app_context():
        while not stop_event.is_set():
            try:
                _bot.infinity_polling(timeout=20, long_polling_timeout=20)
            except Exception as exc:  # noqa: BLE001
                logging.exception("Telegram polling error: %s", exc)
            if not stop_event.is_set():
                stop_event.wait(timeout=5)


# NOTE(agents): _register_handlers wires the command and message callbacks to the bot instance.
def _register_handlers(bot: TeleBot, app: Flask) -> None:
    """Register command handlers and callbacks for the Telegram bot."""

    if types is None:
        return

    # NOTE(agents): _build_mode_keyboard constructs the inline keyboard shared between commands.
    def _build_mode_keyboard() -> types.InlineKeyboardMarkup:
        """Return inline keyboard allowing users to switch response modes."""

        keyboard = types.InlineKeyboardMarkup()
        buttons = [
            types.InlineKeyboardButton(text=label, callback_data=f"mode:{mode}")
            for mode, label in AVAILABLE_MODES.items()
        ]
        keyboard.add(*buttons)
        keyboard.add(types.InlineKeyboardButton(text="Начать новый диалог", callback_data="dialog:new"))
        return keyboard

    # NOTE(agents): _compose_full_name centralises string building from Telegram user data.
    def _compose_full_name(first_name: Optional[str], last_name: Optional[str]) -> str:
        """Return a human friendly representation of a Telegram name."""

        parts = [first_name or "", last_name or ""]
        return " ".join(part for part in parts if part).strip()

    # NOTE(agents): _extract_full_name composes a readable name from Telegram message data.
    def _extract_full_name(message) -> str:
        """Return full name string built from Telegram message metadata."""

        user = message.from_user
        return _compose_full_name(getattr(user, "first_name", ""), getattr(user, "last_name", ""))

    # NOTE(agents): _get_user obtains or creates the database record for the Telegram sender.
    def _get_user(message):
        """Return the persisted user instance representing the message sender."""

        if message.from_user is None:
            return None
        telegram_id = str(message.from_user.id)
        username = message.from_user.username
        full_name = _extract_full_name(message)
        return user_service.get_or_create_user(telegram_id, username, full_name)

    # NOTE(agents): _ensure_active verifies the user still has access before processing commands.
    def _ensure_active(user) -> bool:
        """Return ``True`` if user is active, otherwise send a warning and return ``False``."""

        if user.is_active:
            return True
        bot.send_message(int(user.telegram_id), "Ваш доступ к боту ограничен администратором.")
        return False

    @bot.message_handler(commands=["start"])
    # NOTE(agents): handle_start greets the user and registers them in the system.
    def handle_start(message):  # type: ignore[no-untyped-def]
        """Welcome message handler that also ensures user existence."""

        with app.app_context():
            user = _get_user(message)
            if user is None:
                return
            if not _ensure_active(user):
                return
            text = (
                "Добро пожаловать! Отправьте сообщение, и я перешлю его модели.\n"
                "Используйте /settings чтобы выбрать режим работы."
            )
            bot.send_message(message.chat.id, text, reply_markup=_build_mode_keyboard())

    @bot.message_handler(commands=["help"])
    # NOTE(agents): handle_help provides instructions for available commands.
    def handle_help(message):  # type: ignore[no-untyped-def]
        """Send the help text describing basic commands."""

        with app.app_context():
            user = _get_user(message)
            if user is None or not _ensure_active(user):
                return
            text = (
                "Доступные команды:\n"
                "/start — начать работу и зарегистрироваться;\n"
                "/help — подсказка по управлению;\n"
                "/settings — выбор режима и сброс диалога."
            )
            bot.send_message(message.chat.id, text, reply_markup=_build_mode_keyboard())

    @bot.message_handler(commands=["settings"])
    # NOTE(agents): handle_settings offers mode switching without sending additional instructions.
    def handle_settings(message):  # type: ignore[no-untyped-def]
        """Display keyboard allowing the user to change the response mode."""

        with app.app_context():
            user = _get_user(message)
            if user is None or not _ensure_active(user):
                return
            text = "Выберите режим работы модели или начните новый диалог."
            bot.send_message(message.chat.id, text, reply_markup=_build_mode_keyboard())

    @bot.callback_query_handler(func=lambda call: call.data.startswith("mode:"))
    # NOTE(agents): handle_mode_change persists the selected mode for subsequent requests.
    def handle_mode_change(call):  # type: ignore[no-untyped-def]
        """Update user mode based on inline keyboard selection."""

        with app.app_context():
            user = user_service.get_or_create_user(
                str(call.from_user.id),
                call.from_user.username,
                _compose_full_name(getattr(call.from_user, "first_name", ""), getattr(call.from_user, "last_name", "")),
            )
            if not _ensure_active(user):
                bot.answer_callback_query(call.id, "Доступ ограничен")
                return
            mode = call.data.split(":", 1)[1]
            user_service.update_user_mode(user, mode)
            bot.answer_callback_query(call.id, text=f"Режим '{AVAILABLE_MODES.get(mode, mode)}' активирован")
            bot.send_message(
                call.message.chat.id,
                f"Режим изменён на: {AVAILABLE_MODES.get(mode, mode)}",
            )

    @bot.callback_query_handler(func=lambda call: call.data == "dialog:new")
    # NOTE(agents): handle_new_dialog resets session history when the user requests a fresh start.
    def handle_new_dialog(call):  # type: ignore[no-untyped-def]
        """Clear conversation history and prepare a new dialog session."""

        with app.app_context():
            user = user_service.get_or_create_user(
                str(call.from_user.id),
                call.from_user.username,
                _compose_full_name(getattr(call.from_user, "first_name", ""), getattr(call.from_user, "last_name", "")),
            )
            dialog_service.reset_active_sessions(user)
            bot.answer_callback_query(call.id, text="Диалог очищен")
            bot.send_message(call.message.chat.id, "Начинаем новый диалог. Жду ваш вопрос!")

    @bot.message_handler(content_types=["text"])
    # NOTE(agents): handle_text proxies user prompts to OpenAI and returns the result.
    def handle_text(message):  # type: ignore[no-untyped-def]
        """Process free form text messages and forward them to the LLM."""

        with app.app_context():
            user = _get_user(message)
            if user is None or not _ensure_active(user):
                return
            try:
                response = openai_service.send_user_message(user, message.text)
            except openai_service.OpenAIServiceError as exc:
                logging.error("Failed to send message to OpenAI: %s", exc)
                bot.send_message(message.chat.id, "Сервис временно недоступен, попробуйте позже.")
                return
            bot.send_message(message.chat.id, response, reply_markup=_build_mode_keyboard())

# NOTE(agents): stop_bot_polling allows the application to stop the Telegram polling loop during shutdown.
def stop_bot_polling() -> None:
    """Request the Telegram bot to stop polling."""

    if TeleBot is None or _bot is None:
        return
    _bot.stop_polling()

