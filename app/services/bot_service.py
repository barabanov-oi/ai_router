"""Сервис управления Telegram-ботом."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from logging import Logger
from typing import Iterable, Optional

from flask import Flask, current_app
from telebot import TeleBot, types

from ..models import Dialog, MessageLog, ModelConfig, User, db
from .openai_service import OpenAIService
from .settings_service import SettingsService


# NOTE[agent]: Набор режимов генерации, доступных пользователю в боте.
MODE_DEFINITIONS = {
    "default": {
        "title": "Стандартный ответ",
        "system": "Ты дружелюбный и полезный ассистент.",
    },
    "concise": {
        "title": "Кратко",
        "system": "Отвечай кратко и по существу.",
        "temperature": 0.7,
        "max_tokens": 256,
    },
    "detailed": {
        "title": "Развёрнуто",
        "system": "Давай развёрнутые и подробные ответы с пояснениями.",
        "temperature": 1.1,
        "max_tokens": 768,
    },
}


# NOTE[agent]: Класс инкапсулирует запуск бота, обработку команд и диалогов.
class TelegramBotManager:
    """Управляет жизненным циклом Telegram-бота и обработкой сообщений."""

    def __init__(self, app: Flask | None = None) -> None:
        """Подготавливает менеджер и вспомогательные сервисы."""

        self._settings = SettingsService()
        self._openai = OpenAIService()
        self._bot: Optional[TeleBot] = None
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._app: Flask | None = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Сохраняет ссылку на Flask-приложение для фоновых потоков."""

        self._app = app

    # NOTE[agent]: Метод проверяет активность бота.
    def is_running(self) -> bool:
        """Возвращает True, если бот уже запущен."""

        return self._polling_thread is not None and self._polling_thread.is_alive()

    # NOTE[agent]: Запуск бота в режиме polling.
    def start_polling(self) -> None:
        """Запускает бота в режиме polling в отдельном потоке."""

        if self.is_running():
            self._get_logger().info("Бот уже запущен")
            return

        token = self._settings.get("telegram_bot_token")
        if not token:
            raise RuntimeError("Telegram bot token is not configured")

        self._bot = self._create_bot(token)
        self._stop_event.clear()
        self._polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._polling_thread.start()
        self._get_logger().info("Запущен polling Telegram-бота")

    # NOTE[agent]: Остановка бота и завершение фонового потока.
    def stop(self) -> None:
        """Останавливает работу бота."""

        self._stop_event.set()
        if self._bot:
            try:
                self._bot.stop_polling()
            except Exception:  # pylint: disable=broad-except
                self._get_logger().exception("Ошибка при остановке polling")
        self._bot = None
        if self._polling_thread and self._polling_thread.is_alive():
            self._polling_thread.join(timeout=5)
        self._polling_thread = None
        self._get_logger().info("Polling бота остановлен")

    # NOTE[agent]: Настройка webhook: установка URL и создание экземпляра бота.
    def start_webhook(self) -> str:
        """Настраивает webhook и возвращает URL для проверки."""

        token = self._settings.get("telegram_bot_token")
        webhook_url = self._settings.get("webhook_url")
        if not token or not webhook_url:
            raise RuntimeError("Webhook url или token не настроены")
        self.stop()
        self._bot = self._create_bot(token)
        self._bot.remove_webhook()
        time.sleep(0.5)
        if not self._bot.set_webhook(url=webhook_url):
            raise RuntimeError("Не удалось установить webhook")
        self._get_logger().info("Webhook установлен: %s", webhook_url)
        return webhook_url

    # NOTE[agent]: Вебхук использует этот метод для обработки обновлений.
    def process_webhook_update(self, data: dict) -> None:
        """Передаёт обновление из Flask в TeleBot."""

        if not self._bot:
            token = self._settings.get("telegram_bot_token")
            if not token:
                self._get_logger().error("Невозможно обработать webhook без токена")
                return
            self._bot = self._create_bot(token)
        update = types.Update.de_json(data)
        self._bot.process_new_updates([update])

    # NOTE[agent]: Внутренний цикл polling с устойчивостью к ошибкам.
    def _polling_loop(self) -> None:
        """Запускает TeleBot в бесконечном цикле с перезапуском при ошибке."""

        assert self._bot is not None
        while not self._stop_event.is_set():
            try:
                with self._app_context():
                    self._bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception:  # pylint: disable=broad-except
                self._get_logger().exception("Ошибка в polling, перезапуск через 5 секунд")
                time.sleep(5)

    # NOTE[agent]: Создание экземпляра TeleBot и регистрация обработчиков.
    def _create_bot(self, token: str) -> TeleBot:
        """Создаёт экземпляр TeleBot и регистрирует обработчики."""

        bot = TeleBot(token, parse_mode="HTML")

        @bot.message_handler(commands=["start"])
        def handle_start(message: types.Message) -> None:
            # NOTE[agent]: Обработчик команды /start приветствует пользователя и фиксирует его в базе.
            """Обрабатывает команду /start."""
            with self._app_context():
                self._handle_start(message)

        @bot.message_handler(commands=["help"])
        def handle_help(message: types.Message) -> None:
            # NOTE[agent]: Обработчик команды /help отправляет подсказку.
            """Обрабатывает команду /help."""
            with self._app_context():
                self._handle_help(message)

        @bot.message_handler(commands=["settings"])
        def handle_settings(message: types.Message) -> None:
            # NOTE[agent]: Обработчик показывает режимы и позволяет выбрать.
            """Обрабатывает команду /settings."""
            with self._app_context():
                self._handle_settings(message)

        @bot.callback_query_handler(func=lambda call: call.data.startswith("mode:"))
        def handle_mode_change(call: types.CallbackQuery) -> None:
            # NOTE[agent]: Обработчик смены режима переписывает настройку пользователя.
            """Реагирует на выбор режима ответа."""
            with self._app_context():
                self._handle_mode_change(call)

        @bot.callback_query_handler(func=lambda call: call.data == "dialog:new")
        def handle_new_dialog(call: types.CallbackQuery) -> None:
            # NOTE[agent]: Обработчик завершает текущий диалог и открывает новый.
            """Сбрасывает текущий контекст диалога."""
            with self._app_context():
                self._handle_new_dialog(call)

        @bot.message_handler(content_types=["text"])
        def handle_text(message: types.Message) -> None:
            # NOTE[agent]: Основной обработчик, который направляет запрос к LLM.
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
            self._bot.send_message(chat_id=call.message.chat.id, text=f"Новый режим: {MODE_DEFINITIONS[user.preferred_mode]['title']}")

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
                self._bot.send_message(chat_id=message.chat.id, text="Ваш доступ к боту ограничен. Обратитесь к администратору.")
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

    # NOTE[agent]: Формирует контекст диалога для передачи в OpenAI.
    def _build_openai_messages(self, dialog: Dialog, new_message: MessageLog) -> Iterable[dict[str, str]]:
        """Создаёт список сообщений для OpenAI API."""

        mode = MODE_DEFINITIONS.get(new_message.mode, MODE_DEFINITIONS["default"])
        system_prompt = mode.get("system", MODE_DEFINITIONS["default"]["system"])
        yield {"role": "system", "content": system_prompt}

        logs = (
            MessageLog.query.filter_by(dialog_id=dialog.id)
            .order_by(MessageLog.message_index.asc())
            .all()
        )
        for log in logs:
            yield {"role": "user", "content": log.user_message}
            if log.llm_response:
                yield {"role": "assistant", "content": log.llm_response}

    # NOTE[agent]: Вызов OpenAI API и обработка ответа.
    def _query_llm(self, dialog: Dialog, log_entry: MessageLog) -> str:
        """Отправляет контекст в OpenAI и возвращает ответ."""

        mode = MODE_DEFINITIONS.get(log_entry.mode, MODE_DEFINITIONS["default"])
        model_config = self._get_model_config(mode)
        messages = list(self._build_openai_messages(dialog, log_entry))
        data = self._openai.send_chat_request(messages=messages, model_config=model_config)
        return self._openai.extract_message(data, log_entry)

    # NOTE[agent]: Создаёт inline-клавиатуру для управления диалогом.
    def _build_inline_keyboard(self) -> types.InlineKeyboardMarkup:
        """Возвращает клавиатуру с кнопкой нового диалога."""

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton(text="Начать новый диалог", callback_data="dialog:new"))
        return keyboard

    # NOTE[agent]: Получение или создание пользователя в базе.
    def _get_or_create_user(self, telegram_user: types.User) -> User:
        """Ищет пользователя по Telegram ID и создаёт при отсутствии."""

        full_name = " ".join(filter(None, [telegram_user.first_name, telegram_user.last_name])) or None
        user = User.query.filter_by(telegram_id=str(telegram_user.id)).first()
        if user:
            if telegram_user.username and user.username != telegram_user.username:
                user.username = telegram_user.username
            if full_name and user.full_name != full_name:
                user.full_name = full_name
            db.session.commit()
            return user
        user = User(
            telegram_id=str(telegram_user.id),
            username=telegram_user.username,
            full_name=full_name,
        )
        db.session.add(user)
        db.session.commit()
        return user

    # NOTE[agent]: Получение активного диалога пользователя.
    def _get_active_dialog(self, user: User) -> Optional[Dialog]:
        """Возвращает текущий активный диалог пользователя."""

        return Dialog.query.filter_by(user_id=user.id, is_active=True).order_by(Dialog.started_at.desc()).first()

    # NOTE[agent]: Комбинация настроек модели с параметрами режима.
    def _get_model_config(self, mode_definition: dict) -> dict:
        """Формирует конфигурацию запроса к OpenAI."""

        settings_model_id = self._settings.get("active_model_id")
        query = ModelConfig.query
        if settings_model_id:
            try:
                model_id = int(settings_model_id)
            except ValueError:
                model_id = None
            if model_id is not None:
                model = query.filter_by(id=model_id).first()
            else:
                model = None
        else:
            model = query.filter_by(is_default=True).first()
        if not model:
            model = query.first()
        base_config = (
            model.to_openai_kwargs() if model else {"model": OpenAIService.DEFAULT_MODEL}
        )
        customized = base_config.copy()
        if "temperature" in mode_definition:
            customized["temperature"] = mode_definition["temperature"]
        if "max_tokens" in mode_definition:
            customized["max_tokens"] = mode_definition["max_tokens"]
        return customized

    def _get_logger(self) -> Logger:
        """Возвращает логгер, доступный в текущем или сохранённом контексте."""

        if self._app is not None:
            return self._app.logger
        try:
            return current_app.logger
        except RuntimeError as exc:  # pragma: no cover - защита от некорректного использования
            raise RuntimeError("Менеджер бота не привязан к приложению Flask") from exc

    @contextmanager
    def _app_context(self):
        """Создаёт контекст приложения для фоновых потоков."""

        app = self._app
        if app is None:
            try:
                with current_app.app_context():
                    yield
                return
            except RuntimeError as exc:  # pragma: no cover - защита от некорректного использования
                raise RuntimeError("Менеджер бота не привязан к приложению Flask") from exc
        with app.app_context():
            yield
