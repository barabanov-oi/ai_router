"""Сервис управления Telegram-ботом."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from logging import Logger
from typing import Optional

from flask import Flask, current_app
from telebot import TeleBot, types

from ..services.llm_service import LLMService
from ..services.settings_service import SettingsService
from .dialog_management import DialogManagementMixin
from .message_handlers import MessageHandlingMixin


# NOTE[agent]: Исключение для сигнализации о зависшем polling-потоке.
class PollingStopTimeoutError(RuntimeError):
    """Исключение, сигнализирующее о незавершившемся потоке polling."""


class BotLifecycleMixin:
    """Содержит операции запуска, остановки и инфраструктуру бота."""

    # NOTE[agent]: Метод проверяет активность бота.
    def is_running(self) -> bool:
        """Возвращает True, если бот уже запущен."""

        return self._polling_thread is not None and self._polling_thread.is_alive()

    # NOTE[agent]: Запуск бота в режиме polling.
    def start_polling(self) -> None:
        """Запускает бота в режиме polling в отдельном потоке."""

        self._cleanup_completed_polling_thread()

        if self._polling_thread is not None and self._stop_event.is_set():
            message = (
                "Невозможно запустить polling: предыдущая остановка ещё выполняется"
            )
            self._get_logger().error(message)
            raise RuntimeError(message)

        if self.is_running():
            self._get_logger().info("Бот уже запущен")
            return

        if self._polling_thread is not None:
            try:
                self.stop()
            except PollingStopTimeoutError as exc:
                message = (
                    "Невозможно запустить polling: предыдущий поток ещё завершается"
                )
                self._get_logger().error(message)
                raise RuntimeError(message) from exc

        token = self._settings.get("telegram_bot_token")
        if not token:
            raise RuntimeError("Telegram bot token is not configured")

        self._bot = self._create_bot(token)
        self._stop_event.clear()
        self._polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._polling_thread.start()
        self._get_logger().info("Запущен polling Telegram-бота")

    # NOTE[agent]: Остановка бота и завершение фонового потока.
    def stop(self, timeout: float = 5.0, *, max_wait: Optional[float] = None) -> None:
        """Останавливает работу бота.

        Args:
            timeout: Время ожидания завершения потока polling.
            max_wait: Максимальное общее время ожидания завершения потока.

        Raises:
            PollingStopTimeoutError: Если поток polling не успел завершиться.
        """

        self._stop_event.set()
        bot = self._bot
        if bot:
            try:
                bot.stop_polling()
            except Exception:  # pylint: disable=broad-except
                self._get_logger().exception("Ошибка при остановке polling")

        thread = self._polling_thread
        if thread and thread.is_alive():
            wait_started = time.monotonic()
            deadline = (
                None if max_wait is None else wait_started + max(max_wait, 0.0)
            )
            interval = max(timeout, 0.1)
            attempt = 0

            while thread.is_alive():
                join_timeout = interval
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    join_timeout = min(join_timeout, remaining)
                attempt += 1
                thread.join(timeout=join_timeout)
                if thread.is_alive():
                    self._get_logger().warning(
                        "Поток polling %s всё ещё завершается (попытка %d)",
                        thread.name,
                        attempt,
                    )

            if thread.is_alive():
                elapsed = time.monotonic() - wait_started
                error = PollingStopTimeoutError(
                    f"Поток polling не завершился за {elapsed:.1f} секунды"
                )
                self._get_logger().error(
                    "Поток polling %s не завершился за %.1f секунды",
                    thread.name,
                    elapsed,
                )
                self._notify_polling_error(error)
                raise error

        self._cleanup_completed_polling_thread()

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
            except Exception as exc:  # pylint: disable=broad-except
                self._get_logger().exception("Ошибка в polling, перезапуск через 5 секунд")
                self._notify_polling_error(exc)
                time.sleep(5)

    # NOTE[agent]: Возвращает логгер, привязанный к Flask приложению.
    def _get_logger(self) -> Logger:
        """Возвращает логгер, доступный в текущем или сохранённом контексте."""

        if self._app is not None:
            return self._app.logger
        try:
            return current_app.logger
        except RuntimeError as exc:  # pragma: no cover - защита от некорректного использования
            raise RuntimeError("Менеджер бота не привязан к приложению Flask") from exc

    # NOTE[agent]: Создаёт контекст приложения для фоновых потоков.
    @contextmanager
    def _app_context(self):
        """Создаёт контекст приложения для фоновых потоков."""

        app: Optional[Flask] = self._app
        if app is None:
            try:
                with current_app.app_context():
                    yield
                return
            except RuntimeError as exc:  # pragma: no cover - защита от некорректного использования
                raise RuntimeError("Менеджер бота не привязан к приложению Flask") from exc
        with app.app_context():
            yield

    # NOTE[agent]: Сохраняет ссылку на Flask-приложение для фоновых потоков.
    def init_app(self, app: Flask) -> None:
        """Сохраняет ссылку на Flask-приложение."""

        self._app = app

    # NOTE[agent]: Оповещает администраторов об ошибке polling, если поддерживается.
    def _notify_polling_error(self, exception: Exception) -> None:
        """Отправляет уведомление об ошибке polling при наличии подписчиков."""

        notifier = getattr(self, "_notify_error_subscribers", None)
        if callable(notifier):
            try:
                notifier(message=None, exception=exception)
            except Exception:  # pylint: disable=broad-except
                self._get_logger().exception(
                    "Не удалось отправить уведомление об ошибке polling"
                )

    # NOTE[agent]: Завершает остановку polling, если поток уже завершился.
    def _cleanup_completed_polling_thread(self) -> None:
        """Сбрасывает состояние после остановки polling, когда поток завершён."""

        thread = self._polling_thread
        if thread is None:
            return
        if thread.is_alive():
            return
        self._polling_thread = None
        self._stop_event = threading.Event()
        self._bot = None
        self._get_logger().info("Polling бота остановлен")


# NOTE[agent]: Класс инкапсулирует запуск бота, обработку команд и диалогов.
class TelegramBotManager(BotLifecycleMixin, MessageHandlingMixin, DialogManagementMixin):
    """Управляет жизненным циклом Telegram-бота и обработкой сообщений."""

    def __init__(self, app: Optional[Flask] = None) -> None:
        """Подготавливает менеджер и вспомогательные сервисы."""

        self._settings = SettingsService()
        self._llm = LLMService()
        self._bot: Optional[TeleBot] = None
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._app: Optional[Flask] = None
        if app is not None:
            self.init_app(app)
