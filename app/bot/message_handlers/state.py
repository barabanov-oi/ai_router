"""Утилиты управления состоянием паузы бота."""

from __future__ import annotations

from telebot import types

DEFAULT_PAUSE_MESSAGE = "Бот временно недоступен. Пожалуйста, попробуйте позже."


class BotPauseStateMixin:
    """Инкапсулирует проверки и ответы для режима паузы."""

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
