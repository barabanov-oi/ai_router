"""Миксин с утилитами для управления диалогами Telegram-бота."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from telebot import types

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
        return self._llm.complete_chat(
            model=model,
            payload=model_payload,
            messages=messages,
            log_entry=log_entry,
        )

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
