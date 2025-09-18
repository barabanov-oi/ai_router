"""Инициализация телеграм-бота."""

from __future__ import annotations

from flask import Flask, current_app
from telebot import TeleBot, types

from app.models import ModelConfig
from app.services import conversations, openai_client, settings

MODES = {
    "brief": "Краткий ответ",
    "detailed": "Развёрнутый ответ",
}
"""Доступные режимы ответа модели."""

MODE_PROMPTS = {
    "brief": "Отвечай максимально кратко, используя не более двух предложений.",
    "detailed": "Давай развёрнутые и подробные ответы с пояснениями и примерами, если это уместно.",
}
"""Системные подсказки для режимов ответа."""


def _get_default_model() -> ModelConfig | None:
    """Возвращает модель по умолчанию."""

    model = ModelConfig.query.filter_by(is_default=True, is_active=True).first()
    if model:
        return model
    return ModelConfig.query.filter_by(is_active=True).first()


def _get_user_mode(user_id: int) -> str:
    """Возвращает текущий режим пользователя."""

    return settings.get_setting(f"user_mode_{user_id}", "detailed") or "detailed"


def _set_user_mode(user_id: int, mode: str) -> None:
    """Сохраняет режим пользователя."""

    settings.set_setting(f"user_mode_{user_id}", mode)


def _build_keyboard(mode: str) -> types.InlineKeyboardMarkup:
    """Создаёт inline-клавиатуру для диалога."""

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Начать новый диалог", callback_data="new_dialog"))
    for key, label in MODES.items():
        prefix = "✓ " if key == mode else ""
        keyboard.add(types.InlineKeyboardButton(f"{prefix}{label}", callback_data=f"mode_{key}"))
    return keyboard


def _format_help_message() -> str:
    """Возвращает текст подсказки для пользователя."""

    return (
        "Я помогу вам взаимодействовать с LLM.\n"
        "Доступные команды:\n"
        "/start — начать общение\n"
        "/help — помощь\n"
        "/settings — показать текущие настройки"
    )


def _model_unavailable_message() -> str:
    """Сообщение пользователю при отсутствии активной модели."""

    return "Нет активной модели для обработки запросов. Обратитесь к администратору."


def _handle_dialogue(
    bot: TeleBot,
    message,
    app: Flask,
) -> None:
    """Обрабатывает текстовые сообщения пользователя."""

    with app.app_context():
        user = conversations.get_or_create_user(message.from_user.id, message.from_user.username)
        if not user.is_active:
            bot.reply_to(message, "Ваш доступ ограничен администратором.")
            return
        conversations.update_user_activity(user)
        mode = _get_user_mode(user.id)
        model = _get_default_model()
        if not model:
            bot.reply_to(message, _model_unavailable_message())
            conversations.append_message(
                conversation=conversations.get_active_conversation(user, mode)
                or conversations.start_new_conversation(user, None, mode),
                user=user,
                user_message=message.text,
                assistant_response=None,
                mode=mode,
            )
            return
        conversation = conversations.get_active_conversation(user, mode)
        if conversation is None:
            conversation = conversations.start_new_conversation(user, model, mode)
        history = conversations.fetch_conversation_history(conversation)
        system_prompt = MODE_PROMPTS.get(mode)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(history)
        messages.append({"role": "user", "content": message.text})
        try:
            result = openai_client.openai_service.send_chat_completion(model, messages)
            reply_text = result["message"]
            usage = result.get("usage", {}).get("total_tokens")
            conversations.append_message(
                conversation=conversation,
                user=user,
                user_message=message.text,
                assistant_response=reply_text,
                mode=mode,
                token_usage=usage,
            )
            bot.send_message(message.chat.id, reply_text, reply_markup=_build_keyboard(mode))
        except Exception as exc:  # pylint: disable=broad-except
            current_app.logger.exception("Ошибка при обращении к OpenAI: %s", exc)
            conversations.append_message(
                conversation=conversation,
                user=user,
                user_message=message.text,
                assistant_response=None,
                mode=mode,
            )
            bot.reply_to(message, "Произошла ошибка при обработке запроса. Попробуйте позже.")


def create_bot(app: Flask, token: str) -> TeleBot:
    """Создаёт экземпляр TeleBot с зарегистрированными обработчиками."""

    bot = TeleBot(token, parse_mode="HTML")

    @bot.message_handler(commands=["start"])
    def handle_start(message) -> None:
        """Приветствие пользователя и отображение настроек."""

        with app.app_context():
            user = conversations.get_or_create_user(message.from_user.id, message.from_user.username)
            if not user.is_active:
                bot.reply_to(message, "Ваш доступ ограничен администратором.")
                return
            conversations.update_user_activity(user)
            mode = _get_user_mode(user.id)
            text = (
                "Привет! Я бот для работы с LLM.\n"
                "Используйте клавиатуру ниже для управления диалогом."
            )
            bot.send_message(message.chat.id, text, reply_markup=_build_keyboard(mode))

    @bot.message_handler(commands=["help"])
    def handle_help(message) -> None:
        """Отправляет подсказку пользователю."""

        bot.reply_to(message, _format_help_message())

    @bot.message_handler(commands=["settings"])
    def handle_settings(message) -> None:
        """Показывает текущие настройки пользователя."""

        with app.app_context():
            user = conversations.get_or_create_user(message.from_user.id, message.from_user.username)
            mode = _get_user_mode(user.id)
            bot.reply_to(
                message,
                f"Текущий режим: {MODES.get(mode, mode)}",
                reply_markup=_build_keyboard(mode),
            )

    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback(call) -> None:
        """Обрабатывает inline-кнопки пользователя."""

        with app.app_context():
            user = conversations.get_or_create_user(call.from_user.id, call.from_user.username)
            mode = _get_user_mode(user.id)
            if call.data == "new_dialog":
                conversation = conversations.get_active_conversation(user, mode)
                if conversation:
                    conversations.close_conversation(conversation)
                bot.answer_callback_query(call.id, "Диалог сброшен")
                bot.send_message(call.message.chat.id, "Начат новый диалог", reply_markup=_build_keyboard(mode))
            elif call.data.startswith("mode_"):
                new_mode = call.data.split("_", maxsplit=1)[1]
                if new_mode in MODES:
                    _set_user_mode(user.id, new_mode)
                    bot.answer_callback_query(call.id, f"Выбран режим: {MODES[new_mode]}")
                    bot.edit_message_reply_markup(
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=_build_keyboard(new_mode),
                    )
                else:
                    bot.answer_callback_query(call.id, "Неизвестный режим")
            else:
                bot.answer_callback_query(call.id, "Неизвестная команда")

    @bot.message_handler(content_types=["text"])
    def handle_text(message) -> None:
        """Обрабатывает входящий текст."""

        _handle_dialogue(bot, message, app)

    return bot
