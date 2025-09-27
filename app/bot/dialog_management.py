"""Миксин с утилитами для управления диалогами Telegram-бота."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from html import escape as html_escape

from telebot import types
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ..models import Dialog, MessageLog, ModelConfig, User, db
from .bot_modes import MODE_DEFINITIONS


class DialogManagementMixin:
    """Предоставляет методы для работы с пользователями, диалогами и LLM."""

    # NOTE[agent]: Формирует контекст диалога для передачи поставщику LLM.
    def _build_provider_messages(
        self,
        dialog: Dialog,
        new_message: MessageLog,
        system_instruction: Optional[str] = None,
    ) -> Iterable[Dict[str, str]]:
        """Создаёт список сообщений для API выбранного провайдера."""

        mode = MODE_DEFINITIONS.get(new_message.mode, MODE_DEFINITIONS["default"])
        default_prompt = mode.get("system", MODE_DEFINITIONS["default"]["system"])
        system_prompt = system_instruction or default_prompt
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

    # NOTE[agent]: Вызов поставщика LLM и обработка ответа.
    def _query_llm(self, dialog: Dialog, log_entry: MessageLog) -> str:
        """Отправляет контекст провайдеру LLM и возвращает ответ."""

        mode = MODE_DEFINITIONS.get(log_entry.mode, MODE_DEFINITIONS["default"])
        model, model_payload, system_instruction = self._get_model_config(mode)
        messages = list(self._build_provider_messages(dialog, log_entry, system_instruction))
        log_entry.model_id = model.id
        return self._llm.complete_chat(
            model=model,
            payload=model_payload,
            messages=messages,
            log_entry=log_entry,
        )

    # NOTE[agent]: Создаёт inline-клавиатуру для управления диалогом.
    def _build_inline_keyboard(self) -> types.InlineKeyboardMarkup:
        """Возвращает клавиатуру управления диалогами."""

        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton(text="Новый диалог", callback_data="dialog:new"),
            types.InlineKeyboardButton(text="История диалогов", callback_data="dialog:history"),
        )
        return keyboard

    # NOTE[agent]: Формирование клавиатуры истории диалогов.
    def _build_history_keyboard(self, user: User, limit: int = 5) -> types.InlineKeyboardMarkup:
        """Создаёт клавиатуру с последними диалогами пользователя."""

        dialogs = self._get_recent_dialogs(user=user, limit=limit)
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        for dialog in dialogs:
            title = self._format_dialog_title(dialog)
            if dialog.is_active:
                title = f"✅ {title}"
            keyboard.add(
                types.InlineKeyboardButton(
                    text=title,
                    callback_data=f"dialog:switch:{dialog.id}",
                )
            )
        keyboard.add(
            types.InlineKeyboardButton(text="Новый диалог", callback_data="dialog:new"),
        )
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
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            user = User.query.filter_by(telegram_id=str(telegram_user.id)).first()
            if user is None:
                raise
            if telegram_user.username and user.username != telegram_user.username:
                user.username = telegram_user.username
            if full_name and user.full_name != full_name:
                user.full_name = full_name
            db.session.commit()
        return user

    # NOTE[agent]: Получение активного диалога пользователя.
    def _get_active_dialog(self, user: User) -> Optional[Dialog]:
        """Возвращает текущий активный диалог пользователя."""

        return Dialog.query.filter_by(user_id=user.id, is_active=True).order_by(Dialog.started_at.desc()).first()

    # NOTE[agent]: Возвращает последние диалоги пользователя.
    def _get_recent_dialogs(self, user: User, limit: int = 5) -> List[Dialog]:
        """Отбирает последние диалоги пользователя по дате создания."""

        return (
            Dialog.query.filter_by(user_id=user.id)
            .order_by(Dialog.started_at.desc())
            .limit(limit)
            .all()
        )

    # NOTE[agent]: Обновляет активный диалог пользователя.
    def _activate_dialog(self, user: User, dialog: Dialog) -> None:
        """Ставит указанный диалог активным и завершает остальные."""

        active_dialogs = Dialog.query.filter_by(user_id=user.id, is_active=True).all()
        for active in active_dialogs:
            if active.id == dialog.id:
                continue
            active.is_active = False
            active.ended_at = datetime.utcnow()
        dialog.is_active = True
        dialog.ended_at = None
        db.session.commit()

    # NOTE[agent]: Возвращает краткое название диалога.
    def _format_dialog_title(self, dialog: Dialog) -> str:
        """Формирует текстовое название диалога для кнопок истории."""

        base_title = (dialog.title or "").strip()
        placeholder_titles = {"диалог", "новый диалог", "dialog", "new dialog"}
        if base_title and base_title.lower() in placeholder_titles:
            base_title = ""
        if not base_title:
            first_log = (
                MessageLog.query.filter_by(dialog_id=dialog.id)
                .order_by(MessageLog.message_index.asc())
                .first()
            )
            base_title = (first_log.user_message if first_log else f"Диалог #{dialog.id}") or ""
        prepared = " ".join(base_title.split())
        if len(prepared) > 40:
            prepared = f"{prepared[:40]}…"
        return prepared or f"Диалог #{dialog.id}"

    # NOTE[agent]: Подсчитывает накопленное использование токенов.
    def _calculate_dialog_usage(
        self,
        dialog: Dialog,
        model_id: Optional[int] = None,
    ) -> Tuple[int, int, int]:
        """Возвращает суммарные input/output/total токены в диалоге.

        Args:
            dialog: Диалог, для которого требуется собрать статистику.
            model_id: Идентификатор модели для фильтрации или None для всех моделей.

        Returns:
            Кортеж из суммарных prompt, completion и total токенов.
        """

        query = db.session.query(
            func.coalesce(func.sum(MessageLog.prompt_tokens), 0),
            func.coalesce(func.sum(MessageLog.completion_tokens), 0),
            func.coalesce(func.sum(MessageLog.tokens_used), 0),
        ).filter(MessageLog.dialog_id == dialog.id)
        if model_id is not None:
            query = query.filter(MessageLog.model_id == model_id)
        prompt_sum, completion_sum, total_sum = query.one()
        return int(prompt_sum), int(completion_sum), int(total_sum)

    # NOTE[agent]: Метод определяет актуальный лимит токенов для диалога.
    def _determine_effective_dialog_limit(
        self,
        *,
        dialog: Dialog,
        log_entry: Optional[MessageLog] = None,
    ) -> Optional[int]:
        """Определяет, какой лимит токенов применим к диалогу.

        Args:
            dialog: Диалог, для которого необходимо вычислить ограничение.
            log_entry: Последняя запись лога, связанная с ответом LLM.

        Returns:
            Положительный лимит токенов или None, если ограничение не задано.
        """

        configured_limit: Optional[int] = None
        settings_service = getattr(self, "_settings", None)
        if settings_service is not None and hasattr(settings_service, "get_int"):
            configured_limit = settings_service.get_int("dialog_token_limit")
        if configured_limit is not None and configured_limit <= 0:
            configured_limit = None

        source_entry = log_entry
        if source_entry is None:
            source_entry = (
                MessageLog.query.filter_by(dialog_id=dialog.id)
                .filter(MessageLog.model_id.isnot(None))
                .order_by(MessageLog.message_index.desc())
                .first()
            )
        model_limit: Optional[int] = None
        if source_entry and source_entry.model:
            raw_limit = int(source_entry.model.dialog_token_limit or 0)
            if raw_limit > 0:
                model_limit = raw_limit

        limits = [value for value in (configured_limit, model_limit) if value and value > 0]
        if not limits:
            return None
        return min(limits)

    # NOTE[agent]: Формирует строку с информацией об использовании токенов.
    def _format_usage_summary(
        self, dialog: Dialog, log_entry: MessageLog
    ) -> Tuple[str, int, Optional[int]]:
        """Возвращает текст с информацией об израсходованных токенах.

        Args:
            dialog: Диалог, для которого требуется статистика.
            log_entry: Запись лога последнего ответа LLM.

        Returns:
            Кортеж из текстового описания, общего числа токенов и лимита.
        """

        prompt_total, completion_total, total_tokens = self._calculate_dialog_usage(dialog)
        total_limit = self._determine_effective_dialog_limit(dialog=dialog, log_entry=log_entry)
        limit_display: int | str = total_limit if total_limit is not None else "∞"
        def _italic(value: int | str) -> str:
            """Возвращает значение, выделенное курсивом в HTML."""

            return f"<i>{html_escape(str(value))}</i>"

        prefix = "📊 Использовано токенов:"
        question_label = " (вопрос: "
        answer_label = ", ответ: "
        closing_bracket = ")"
        total_text = _italic(f"{total_tokens} / {limit_display}")
        prompt_text = _italic(prompt_total)
        completion_text = _italic(completion_total)
        summary_text = (
            f"{html_escape(prefix)} "
            f"{total_text}"
            f"{html_escape(question_label)}"
            f"{prompt_text}"
            f"{html_escape(answer_label)}"
            f"{completion_text}"
            f"{html_escape(closing_bracket)}"
        )
        return summary_text, total_tokens, total_limit

    # NOTE[agent]: Определяет, как сослаться на последнее сообщение диалога.
    def _get_last_message_reference(self, dialog: Dialog) -> Tuple[Optional[int], Optional[str]]:
        """Возвращает идентификатор сообщения и текст последнего сообщения."""

        if not dialog.telegram_chat_id:
            return None, None
        last_response_log = (
            MessageLog.query.filter_by(dialog_id=dialog.id)
            .filter(
                (MessageLog.assistant_message_id.isnot(None))
                | (MessageLog.llm_response.isnot(None))
            )
            .order_by(MessageLog.message_index.desc())
            .first()
        )
        if last_response_log:
            if last_response_log.assistant_message_id:
                return last_response_log.assistant_message_id, None
            if last_response_log.llm_response:
                return None, last_response_log.llm_response[-150:]
        last_log = (
            MessageLog.query.filter_by(dialog_id=dialog.id)
            .order_by(MessageLog.message_index.desc())
            .first()
        )
        if not last_log:
            return None, None
        last_text = last_log.llm_response or last_log.user_message
        if last_text:
            return None, last_text[-150:]
        return None, None

    # NOTE[agent]: Комбинация настроек модели с параметрами режима.
    def _get_model_config(self, mode_definition: dict) -> Tuple[ModelConfig, dict, Optional[str]]:
        """Формирует конфигурацию запроса к выбранному провайдеру."""

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
        if not model:
            raise RuntimeError("В системе не настроены конфигурации моделей")
        base_config = model.to_request_options()
        customized = base_config.copy()
        if "temperature" in mode_definition:
            customized["temperature"] = mode_definition["temperature"]
        if "max_tokens" in mode_definition:
            customized["max_tokens"] = mode_definition["max_tokens"]
        instruction = model.system_instruction if model.system_instruction else None
        return model, customized, instruction
