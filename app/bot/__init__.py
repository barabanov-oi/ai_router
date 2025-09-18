"""Телеграм-бот для взаимодействия пользователей с LLM."""

from __future__ import annotations

import logging
from threading import Thread
from typing import Optional

from flask import Flask
from telebot import TeleBot, types

from ..models import ModelPreset, db
from ..services.conversation_service import (
    build_conversation_messages,
    close_conversation,
    get_active_conversation,
    get_or_create_user,
    log_request,
    touch_user,
    update_user_preset,
)
from ..services.openai_service import generate_completion
from ..services.settings_service import get_default_preset, get_setting

LOGGER = logging.getLogger(__name__)


# AGENT: Создаёт экземпляр Telegram-бота и регистрирует обработчики.
def create_bot(app: Flask) -> Optional[TeleBot]:
    """Создать и настроить телеграм-бота.

    Args:
        app (Flask): Flask-приложение для доступа к контексту и конфигурации.

    Returns:
        Optional[TeleBot]: Настроенный бот или ``None``, если токен отсутствует.
    """

    token = app.config.get("TELEGRAM_BOT_TOKEN") or get_setting("telegram_bot_token")
    if not token:
        LOGGER.error("Не указан токен Telegram-бота")
        return None

    bot = TeleBot(token, parse_mode="Markdown")
    register_handlers(bot, app)
    return bot


# AGENT: Запускает поллинг бота в отдельном потоке.
def start_bot_polling(bot: Optional[TeleBot]) -> Optional[Thread]:
    """Запустить бесконечный поллинг телеграм-бота.

    Args:
        bot (Optional[TeleBot]): Экземпляр бота.

    Returns:
        Optional[Thread]: Поток с поллингом или ``None``.
    """

    if bot is None:
        return None

    def _poll() -> None:
        """Выполнять поллинг бота, пока приложение работает."""

        try:
            bot.infinity_polling(skip_pending=True)
        except Exception as error:  # pylint: disable=broad-except
            LOGGER.exception("Ошибка работы телеграм-бота: %s", error)

    thread = Thread(target=_poll, daemon=True)
    thread.start()
    return thread


# AGENT: Регистрирует обработчики команд и сообщений бота.
def register_handlers(bot: TeleBot, app: Flask) -> None:
    """Добавить обработчики команд и сообщений телеграм-бота.

    Args:
        bot (TeleBot): Экземпляр телеграм-бота.
        app (Flask): Flask-приложение для работы с контекстом БД.
    """

    # AGENT: Обрабатывает команду /start, приветствуя пользователя.
    @bot.message_handler(commands=["start"])
    def handle_start(message: types.Message) -> None:
        """Ответить на команду /start и создать пользователя при необходимости."""

        with app.app_context():
            user = get_or_create_user(
                telegram_id=str(message.from_user.id),
                username=message.from_user.username,
                full_name=f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip(),
            )
            touch_user(user)
            conversation = get_active_conversation(user)
            bot.reply_to(
                message,
                (
                    "Привет! Я помогу получить ответы от LLM. "
                    "Просто отправь сообщение, и я передам его модели.\n\n"
                    f"Текущий режим: *{conversation.preset.display_name}*."
                ),
            )

    # AGENT: Отвечает на команду /help подсказками.
    @bot.message_handler(commands=["help"])
    def handle_help(message: types.Message) -> None:
        """Предоставить подсказки по работе с ботом."""

        help_text = (
            "Доступные команды:\n"
            "• /start — начать работу или возобновить диалог.\n"
            "• /settings — выбрать режим ответа.\n"
            "• Кнопка *Начать новый диалог* завершает текущий диалог."
        )
        bot.reply_to(message, help_text)

    # AGENT: Показывает доступные пресеты модели.
    @bot.message_handler(commands=["settings"])
    def handle_settings(message: types.Message) -> None:
        """Показать меню выбора режима работы модели."""

        with app.app_context():
            presets = ModelPreset.query.order_by(ModelPreset.display_name.asc()).all()
        if not presets:
            bot.reply_to(message, "Пресеты моделей ещё не настроены администратором.")
            return
        keyboard = types.InlineKeyboardMarkup()
        for preset in presets:
            keyboard.add(
                types.InlineKeyboardButton(
                    text=preset.display_name,
                    callback_data=f"preset:{preset.id}",
                )
            )
        keyboard.add(types.InlineKeyboardButton(text="Начать новый диалог", callback_data="reset_dialog"))
        bot.reply_to(
            message,
            "Выбери подходящий режим работы модели или начни новый диалог.",
            reply_markup=keyboard,
        )

    # AGENT: Обрабатывает текстовые сообщения пользователей.
    @bot.message_handler(func=lambda msg: bool(msg.text))
    def handle_text(message: types.Message) -> None:
        """Передать сообщение пользователя в модель и вернуть ответ."""

        with app.app_context():
            user = get_or_create_user(
                telegram_id=str(message.from_user.id),
                username=message.from_user.username,
                full_name=f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip(),
            )
            touch_user(user)
            conversation = get_active_conversation(user)
            preset = conversation.preset or user.preferred_preset or get_default_preset()
            messages = build_conversation_messages(conversation)
            messages.append({"role": "user", "content": message.text})
            bot.send_chat_action(message.chat.id, "typing")
            response, usage, error_message = generate_completion(messages, preset)
            if error_message:
                log_request(
                    user=user,
                    conversation=conversation,
                    preset=preset,
                    prompt=message.text,
                    response=None,
                    status="error",
                    error_message=error_message,
                )
                bot.reply_to(
                    message,
                    "Произошла ошибка при обращении к модели. Пожалуйста, попробуйте позже.",
                )
                return

            log_request(
                user=user,
                conversation=conversation,
                preset=preset,
                prompt=message.text,
                response=response,
                status="success",
                prompt_tokens=usage.get("prompt_tokens") if usage else None,
                completion_tokens=usage.get("completion_tokens") if usage else None,
                total_tokens=usage.get("total_tokens") if usage else None,
            )
            if usage and usage.get("total_tokens"):
                user.tokens_used += usage["total_tokens"]
                db.session.commit()
            bot.reply_to(message, response or "Ответ модели отсутствует.")

    # AGENT: Обрабатывает нажатия на inline-кнопки.
    @bot.callback_query_handler(func=lambda call: bool(call.data))
    def handle_callbacks(call: types.CallbackQuery) -> None:
        """Реагировать на выбор пресета или сброс диалога."""

        data = call.data or ""
        with app.app_context():
            user = get_or_create_user(
                telegram_id=str(call.from_user.id),
                username=call.from_user.username,
                full_name=f"{call.from_user.first_name or ''} {call.from_user.last_name or ''}".strip(),
            )
            if data == "reset_dialog":
                conversation = get_active_conversation(user)
                close_conversation(conversation)
                new_conversation = get_active_conversation(user)
                bot.answer_callback_query(call.id, "Новый диалог создан")
                bot.send_message(call.message.chat.id, f"Создан новый диалог: {new_conversation.title}")
                return

            if data.startswith("preset:"):
                preset_id = int(data.split(":", 1)[1])
                preset = ModelPreset.query.get(preset_id)
                if not preset:
                    bot.answer_callback_query(call.id, "Пресет не найден")
                    return
                update_user_preset(user, preset)
                conversation = get_active_conversation(user)
                conversation.preset = preset
                db.session.commit()
                bot.answer_callback_query(
                    call.id,
                    f"Выбран режим: {preset.display_name}",
                )

    # AGENT: Обрабатывает неизвестные типы сообщений.
    @bot.message_handler(content_types=["photo", "video", "document", "audio"])
    def handle_unsupported(message: types.Message) -> None:
        """Сообщить пользователю о неподдерживаемом типе содержимого."""

        bot.reply_to(message, "Пока что я принимаю только текстовые сообщения.")
