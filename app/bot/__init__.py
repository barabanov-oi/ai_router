"""Telegram bot implementation for the ai_router project."""
from __future__ import annotations

import json
import logging
import threading
from typing import Optional

import telebot
import requests
from flask import Response, current_app, request
from telebot import types

from app.services import dialog_service, settings_service, user_service
from app.services.database import DatabaseSessionManager

LOGGER = logging.getLogger(__name__)


class TelegramBotManager:
    """High-level manager that encapsulates Telegram bot lifecycle."""

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        # Комментарий для агентов: Сохраняем менеджер сессий и готовим поля для управления ботом.
        self._session_manager = session_manager
        self._bot: Optional[telebot.TeleBot] = None
        self._bot_token: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running_mode: Optional[str] = None

    def ensure_bot(self) -> Optional[telebot.TeleBot]:
        # Комментарий для агентов: Создаёт нового бота при смене токена и регистрирует обработчики.
        """Ensure telebot instance is configured with latest token."""

        with self._session_manager.session_scope() as session:
            settings = settings_service.get_bot_settings(session)
            token = settings.bot_token
        if not token:
            LOGGER.warning("Токен телеграм-бота не задан")
            return None
        if self._bot is None or self._bot_token != token:
            self._bot = telebot.TeleBot(token, parse_mode="Markdown")
            self._bot_token = token
            # Комментарий для агентов: Проверяем токен, чтобы администратор быстрее обнаружил ошибку конфигурации.
            try:
                response = requests.get(
                    f"https://api.telegram.org/bot{token}/getMe", timeout=5
                )
                response.raise_for_status()
            except requests.RequestException as exc:  # pragma: no cover - network path
                LOGGER.warning("Не удалось проверить токен бота: %s", exc)
            self._register_handlers(self._bot)
        return self._bot

    def start_polling(self) -> bool:
        # Комментарий для агентов: Запускает бесконечный polling в отдельном потоке.
        """Start bot in polling mode inside background thread."""

        with self._lock:
            if self._running_mode == "polling":
                return False
            bot = self.ensure_bot()
            if bot is None:
                raise RuntimeError("Токен бота не настроен")
            bot.remove_webhook()
            self._running_mode = "polling"
            self._thread = threading.Thread(target=self._polling_loop, daemon=True)
            self._thread.start()
            return True

    def start_webhook(self) -> bool:
        # Комментарий для агентов: Настраивает webhook и переключает состояние менеджера.
        """Configure bot webhook using stored settings."""

        with self._session_manager.session_scope() as session:
            settings = settings_service.get_bot_settings(session)
            webhook_url = settings.webhook_url
            secret = settings.webhook_secret
        bot = self.ensure_bot()
        if bot is None:
            raise RuntimeError("Токен бота не настроен")
        if not webhook_url:
            raise RuntimeError("URL вебхука не задан")
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url, secret_token=secret)
        with self._lock:
            self._running_mode = "webhook"
        return True

    def process_webhook(self) -> Response:
        # Комментарий для агентов: Обрабатывает входящие webhook-запросы от Telegram.
        """Process webhook request coming from Telegram servers."""

        bot = self.ensure_bot()
        if bot is None:
            return Response("bot not configured", status=503)
        with self._session_manager.session_scope() as session:
            settings = settings_service.get_bot_settings(session)
            expected_secret = settings.webhook_secret
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if expected_secret and header_secret != expected_secret:
            LOGGER.warning("Получен вебхук с неверным секретом")
            return Response("forbidden", status=403)
        try:
            payload = json.loads(request.get_data().decode("utf-8"))
        except json.JSONDecodeError:
            LOGGER.warning("Получено некорректное тело вебхука")
            return Response("bad request", status=400)
        update = types.Update.de_json(payload)
        bot.process_new_updates([update])
        return Response("ok", status=200)

    def get_status(self) -> str:
        # Комментарий для агентов: Возвращает текущий режим работы бота.
        """Return current running mode for monitoring."""

        with self._lock:
            return self._running_mode or "offline"

    def _polling_loop(self) -> None:
        # Комментарий для агентов: Выполняет бесконечный цикл чтения обновлений.
        """Execute infinity polling loop in background thread."""

        bot = self.ensure_bot()
        if bot is None:
            LOGGER.error("Не удалось запустить бота: токен отсутствует")
            return
        try:
            bot.infinity_polling(skip_pending=True, timeout=20)
        except Exception as exc:  # pragma: no cover - background thread
            LOGGER.exception("Ошибка в polling-цикле бота: %s", exc)
        finally:
            with self._lock:
                self._running_mode = None

    def _register_handlers(self, bot: telebot.TeleBot) -> None:
        # Комментарий для агентов: Регистрирует все команды и обработчики колбэков телеграм-бота.
        """Register command and message handlers for telebot instance."""

        @bot.message_handler(commands=["start"])
        # Комментарий для агентов: Приветствие и первичная регистрация пользователя.
        def handle_start(message: types.Message) -> None:
            """Handle /start command by greeting the user."""

            with current_app.app_context():
                with self._session_manager.session_scope() as session:
                    user = user_service.get_or_create_user(
                        session=session,
                        telegram_id=message.from_user.id,
                        username=message.from_user.username,
                        full_name=message.from_user.full_name,
                    )
                    session.flush()
                    reply = (
                        "Привет! Я бот для работы с LLM."
                        " Отправьте сообщение, и я отвечу."
                    )
                    bot.reply_to(message, reply, reply_markup=self._dialog_keyboard())

        @bot.message_handler(commands=["help"])
        # Комментарий для агентов: Отправляет краткую инструкцию по использованию бота.
        def handle_help(message: types.Message) -> None:
            """Provide short usage instructions."""

            reply = (
                "Используйте /settings для выбора режима ответа."
                " Нажмите кнопку 'Начать новый диалог', чтобы сбросить контекст."
            )
            bot.reply_to(message, reply, reply_markup=self._dialog_keyboard())

        @bot.message_handler(commands=["settings"])
        # Комментарий для агентов: Показывает пользовательские режимы ответа.
        def handle_settings(message: types.Message) -> None:
            """Show inline buttons for selecting response mode."""

            bot.send_message(
                chat_id=message.chat.id,
                text="Выберите режим работы модели:",
                reply_markup=self._settings_keyboard(),
            )

        @bot.callback_query_handler(func=lambda call: call.data == "show_settings")
        # Комментарий для агентов: Вызывается при нажатии кнопки настройки в диалоге.
        def handle_settings_callback(callback: types.CallbackQuery) -> None:
            """Show mode selection buttons from inline keyboard."""

            bot.answer_callback_query(callback.id)
            bot.send_message(
                chat_id=callback.message.chat.id,
                text="Выберите режим работы модели:",
                reply_markup=self._settings_keyboard(),
            )

        @bot.callback_query_handler(func=lambda call: call.data == "new_dialog")
        # Комментарий для агентов: Очищает историю и создаёт новый диалог.
        def handle_new_dialog(callback: types.CallbackQuery) -> None:
            """Reset dialog history and notify the user."""

            with current_app.app_context():
                with self._session_manager.session_scope() as session:
                    user = user_service.get_or_create_user(
                        session=session,
                        telegram_id=callback.from_user.id,
                        username=callback.from_user.username,
                        full_name=callback.from_user.full_name,
                    )
                    dialog_service.reset_dialog(session, user)
                    bot.answer_callback_query(callback.id, "Новый диалог создан")
                    bot.send_message(
                        chat_id=callback.message.chat.id,
                        text="Контекст очищен. Продолжайте переписку.",
                        reply_markup=self._dialog_keyboard(),
                    )

        @bot.callback_query_handler(func=lambda call: call.data.startswith("mode:"))
        # Комментарий для агентов: Сохраняет выбранный пользователем режим ответа.
        def handle_mode(callback: types.CallbackQuery) -> None:
            """Switch response mode for the user."""

            mode = callback.data.split(":", maxsplit=1)[1]
            with current_app.app_context():
                with self._session_manager.session_scope() as session:
                    user = user_service.get_or_create_user(
                        session=session,
                        telegram_id=callback.from_user.id,
                        username=callback.from_user.username,
                        full_name=callback.from_user.full_name,
                    )
                    user.dialog_mode = mode
                    bot.answer_callback_query(callback.id, "Режим обновлён")
                    bot.send_message(
                        chat_id=callback.message.chat.id,
                        text=f"Текущий режим: {self._mode_label(mode)}",
                        reply_markup=self._dialog_keyboard(),
                    )

        @bot.message_handler(content_types=["text"])
        # Комментарий для агентов: Основной обработчик, отправляет запросы в LLM.
        def handle_text(message: types.Message) -> None:
            """Send user message to OpenAI and reply with answer."""

            with current_app.app_context():
                with self._session_manager.session_scope() as session:
                    user = user_service.get_or_create_user(
                        session=session,
                        telegram_id=message.from_user.id,
                        username=message.from_user.username,
                        full_name=message.from_user.full_name,
                    )
                    if not user.is_active:
                        bot.reply_to(message, "Ваш доступ ограничен администратором.")
                        return
                    try:
                        saved_message = dialog_service.send_llm_request(
                            session=session,
                            user=user,
                            user_text=message.text,
                        )
                    except Exception as exc:  # pragma: no cover - network path
                        LOGGER.exception("Не удалось получить ответ от модели: %s", exc)
                        bot.reply_to(
                            message,
                            "Произошла ошибка при обращении к модели. Попробуйте позже.",
                        )
                        return
                    bot.send_message(
                        chat_id=message.chat.id,
                        text=saved_message.assistant_text or "",
                        reply_markup=self._dialog_keyboard(),
                    )

    def _dialog_keyboard(self) -> types.InlineKeyboardMarkup:
        # Комментарий для агентов: Кнопки управления активным диалогом.
        """Return inline keyboard with dialog management buttons."""

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("Начать новый диалог", callback_data="new_dialog"))
        keyboard.add(types.InlineKeyboardButton("Настройки", callback_data="show_settings"))
        return keyboard

    def _settings_keyboard(self) -> types.InlineKeyboardMarkup:
        # Комментарий для агентов: Формирует клавиатуру с режимами ответов.
        """Return inline keyboard for selecting dialog mode."""

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("Краткий ответ", callback_data="mode:short"),
            types.InlineKeyboardButton("Стандарт", callback_data="mode:standard"),
        )
        keyboard.add(
            types.InlineKeyboardButton("Развёрнутый ответ", callback_data="mode:detailed")
        )
        keyboard.add(
            types.InlineKeyboardButton("Новый диалог", callback_data="new_dialog"),
        )
        return keyboard

    def _mode_label(self, mode: str) -> str:
        # Комментарий для агентов: Возвращает локализованное название режима для сообщений пользователю.
        """Return localized label for provided dialog mode."""

        return {
            "short": "Краткий ответ",
            "standard": "Стандартный ответ",
            "detailed": "Развёрнутый ответ",
        }.get(mode, "Стандартный ответ")


__all__ = ["TelegramBotManager"]
