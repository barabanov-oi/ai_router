"""Тесты логики управления жизненным циклом бота."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

# NOTE[agent]: Добавляет корень проекта в путь импорта для unit-тестов.
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.bot.bot_service import BotLifecycleMixin, PollingStopTimeoutError


class _DummyBot:
    """Простейшая заглушка TeleBot для тестов."""

    def __init__(self) -> None:
        self.stopped = False

    # NOTE[agent]: Фиксирует факт вызова остановки polling.
    def stop_polling(self) -> None:
        """Имитация остановки polling."""

        self.stopped = True


class _LifecycleStub(BotLifecycleMixin):
    """Минимальный менеджер для тестирования остановки polling."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._polling_thread: threading.Thread | None = None
        self._bot = _DummyBot()
        self._app = SimpleNamespace(logger=logging.getLogger("tests.bot_service"))

    # NOTE[agent]: Возвращает тестовый логгер для изолированных проверок.
    def _get_logger(self):  # type: ignore[override]
        return self._app.logger


# NOTE[agent]: Проверяет корректность реакции stop() на зависший поток.
def test_stop_raises_if_thread_does_not_finish() -> None:
    """Проверяет, что stop() выбрасывает исключение при зависшем потоке."""

    manager = _LifecycleStub()

    def slow_worker() -> None:
        manager._stop_event.wait()
        time.sleep(0.1)

    thread = threading.Thread(target=slow_worker, name="test-polling", daemon=True)
    manager._polling_thread = thread
    thread.start()

    with pytest.raises(PollingStopTimeoutError):
        manager.stop(timeout=0.01)

    assert manager._polling_thread is thread
    assert manager._bot is not None
    assert manager._stop_event.is_set()

    thread.join(timeout=1)
    manager.stop()

    assert manager._polling_thread is None
    assert manager._bot is None
    assert not manager._stop_event.is_set()


class _FailingStopManager(BotLifecycleMixin):
    """Менеджер, у которого остановка polling всегда завершается тайм-аутом."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._stop_event.set()
        self._polling_thread = SimpleNamespace(is_alive=lambda: True)
        self._settings = SimpleNamespace(get=lambda key: "token" if key == "telegram_bot_token" else None)
        self._bot = None
        self._app = SimpleNamespace(logger=logging.getLogger("tests.bot_service"))

    # NOTE[agent]: Возвращает тестовый логгер для изолированных проверок.
    def _get_logger(self):  # type: ignore[override]
        return self._app.logger

    # NOTE[agent]: Создаёт фиктивного бота вместо TeleBot.
    def _create_bot(self, token: str):  # type: ignore[override]
        return _DummyBot()

    # NOTE[agent]: Имитация неуспешной остановки polling.
    def stop(self, timeout: float = 5.0) -> None:  # type: ignore[override]
        raise PollingStopTimeoutError("previous polling is still stopping")


# NOTE[agent]: Менеджер для проверки повторного запуска после завершения старого потока.
class _RestartableManager(BotLifecycleMixin):
    """Менеджер, который умеет запускать polling после очистки завершённого потока."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._polling_thread: threading.Thread | None = None
        self._settings = SimpleNamespace(
            get=lambda key, default=None: "token"
            if key == "telegram_bot_token"
            else default
        )
        self._bot = None
        self._app = SimpleNamespace(logger=logging.getLogger("tests.bot_service"))
        self.started = threading.Event()

    # NOTE[agent]: Возвращает тестовый логгер.
    def _get_logger(self):  # type: ignore[override]
        return self._app.logger

    # NOTE[agent]: Создаёт заглушку бота вместо TeleBot.
    def _create_bot(self, token: str):  # type: ignore[override]
        return _DummyBot()

    # NOTE[agent]: Упрощённый цикл polling для тестов.
    def _polling_loop(self) -> None:  # type: ignore[override]
        assert self._bot is not None
        self.started.set()


# NOTE[agent]: Проверяет отказ в запуске при незавершённой остановке polling.
def test_start_polling_fails_when_previous_stop_incomplete() -> None:
    """Проверяет, что повторный запуск не выполняется при незавершённой остановке."""

    manager = _FailingStopManager()

    with pytest.raises(RuntimeError) as error:
        manager.start_polling()

    assert "предыдущая остановка ещё выполняется" in str(error.value)
    assert manager._bot is None


# NOTE[agent]: Проверяет очистку завершившегося потока перед повторным запуском.
def test_start_polling_cleans_up_completed_thread() -> None:
    """Убеждается, что завершённый поток очищается и polling запускается заново."""

    manager = _RestartableManager()

    old_thread = threading.Thread(target=lambda: None, name="old-polling")
    old_thread.start()
    old_thread.join()

    manager._polling_thread = old_thread
    manager._stop_event.set()
    manager._bot = _DummyBot()

    manager.start_polling()

    assert manager._polling_thread is not None
    assert manager._polling_thread is not old_thread
    assert not manager._stop_event.is_set()

    manager.started.wait(timeout=1)
    manager.stop()
