"""Маршруты административного интерфейса."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, session, url_for

from ...models import BotCommand, Dialog, LLMProvider, MessageLog, ModelConfig, User, db
from ...bot.bot_service import TelegramBotManager
from ...services.settings_service import SettingsService
from ...services.statistics_service import StatisticsService
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

admin_bp = Blueprint("admin", __name__, url_prefix="/admin", template_folder="../templates")


# NOTE[agent]: Ключ сессии, сигнализирующий об авторизованном администраторе.
ADMIN_SESSION_KEY = "admin_authenticated"


# NOTE[agent]: Обработчик проверяет доступ к маршрутам админ-панели.
@admin_bp.before_request
def ensure_authenticated() -> Optional[Response]:
    """Перенаправляет неавторизованных пользователей на форму входа."""

    endpoint = request.endpoint or ""
    if endpoint.endswith("login") or endpoint.endswith("logout"):
        return None
    if _is_admin_authenticated():
        return None
    next_url = request.url
    return redirect(url_for("admin.login", next=next_url))


# NOTE[agent]: Маршрут отображает и обрабатывает форму входа в админку.
@admin_bp.route("/login", methods=["GET", "POST"])
def login() -> Union[Response, str]:
    """Авторизует администратора на основе настроек приложения."""

    error: Optional[str] = None
    app_login = current_app.config.get("ADMIN_LOGIN")
    app_password = current_app.config.get("ADMIN_PASSWORD")
    credentials_configured = bool(app_login and app_password)
    if request.method == "POST":
        if not credentials_configured:
            error = "Учётные данные администратора не настроены."
        else:
            form_login = request.form.get("login", "").strip()
            form_password = request.form.get("password", "")
            if form_login == app_login and form_password == app_password:
                session[ADMIN_SESSION_KEY] = True
                session["admin_login"] = form_login
                redirect_target = _safe_next_url(request.args.get("next"))
                return redirect(redirect_target)
            error = "Неверный логин или пароль."
    return render_template(
        "admin/login.html",
        error=error,
        credentials_configured=credentials_configured,
    )


# NOTE[agent]: Маршрут завершает сессию администратора.
@admin_bp.route("/logout")
def logout() -> Response:
    """Выходит из админ-панели и очищает сессию пользователя."""

    session.pop(ADMIN_SESSION_KEY, None)
    session.pop("admin_login", None)
    return redirect(url_for("admin.login"))


# NOTE[agent]: Вспомогательная функция проверяет авторизацию в сессии.
def _is_admin_authenticated() -> bool:
    """Сообщает, авторизован ли администратор в текущей сессии."""

    return bool(session.get(ADMIN_SESSION_KEY))


# NOTE[agent]: Вспомогательная функция защищает редирект после логина.
def _safe_next_url(next_url: Optional[str]) -> str:
    """Возвращает безопасный относительный URL для перенаправления."""

    default_url = url_for("admin.dashboard")
    if not next_url:
        return default_url
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return default_url
    if not parsed.path.startswith("/admin"):
        return default_url
    return next_url


# NOTE[agent]: Точка входа в админку отображает ключевые метрики и статус бота.
@admin_bp.route("/")
def dashboard() -> str:
    """Отображает сводную статистику и основные настройки."""

    period = int(request.args.get("days", 7) or 7)
    start_raw = request.args.get("start")
    end_raw = request.args.get("end")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    if start_raw and end_raw:
        try:
            start_date = datetime.strptime(start_raw, "%Y-%m-%d")
            end_date = datetime.strptime(end_raw, "%Y-%m-%d")
            if end_date < start_date:
                start_date, end_date = end_date, start_date
        except ValueError:
            start_date = None
            end_date = None
    stats = StatisticsService().gather(days=period, start=start_date, end=end_date)
    selected_period_days = period
    if start_date and end_date:
        selected_period_days = (end_date - start_date).days + 1
    settings = SettingsService().all_settings()
    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    is_bot_running = bot_manager.is_running() if bot_manager else False
    models = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    provider_titles = LLMProvider.vendor_titles()
    active_model = None
    active_model_id = settings.get("active_model_id", "")
    for model in models:
        if active_model_id and str(model.id) == active_model_id:
            active_model = model
            break
    if active_model is None:
        active_model = next((model for model in models if model.is_default), None)
    start_value = start_date.strftime("%Y-%m-%d") if start_date else ""
    end_value = end_date.strftime("%Y-%m-%d") if end_date else ""
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        period=period,
        start_date=start_date,
        end_date=end_date,
        selected_period_days=selected_period_days,
        settings=settings,
        is_bot_running=is_bot_running,
        models=models,
        active_model=active_model,
        start_value=start_value,
        end_value=end_value,
        provider_titles=provider_titles,
    )


# NOTE[agent]: Страница управления пользователями позволяет изменять активность.
@admin_bp.route("/users", methods=["GET"])
def manage_users() -> Union[Response, str]:
    """Отображает список пользователей."""

    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)


# NOTE[agent]: Маршрут переключает флаг активности пользователя.
@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
def toggle_user(user_id: int) -> Response:
    """Переключает доступ пользователя к боту."""

    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    return redirect(url_for("admin.manage_users"))


# NOTE[agent]: Страница с журналом сообщений для аудита.
@admin_bp.route("/logs")
def logs() -> str:
    """Показывает последние сообщения пользователей и ответы LLM."""

    limit = int(request.args.get("limit", 50) or 50)
    dialog_limit = int(request.args.get("dialog_limit", 50) or 50)
    message_stats = (
        db.session.query(
            MessageLog.dialog_id.label("dialog_id"),
            func.count(MessageLog.id).label("message_count"),
            func.coalesce(func.sum(MessageLog.tokens_used), 0).label("tokens_spent"),
            func.coalesce(func.sum(MessageLog.prompt_tokens), 0).label("prompt_tokens_spent"),
            func.coalesce(func.sum(MessageLog.completion_tokens), 0).label("completion_tokens_spent"),
        )
        .group_by(MessageLog.dialog_id)
        .subquery()
    )
    first_message_subquery = (
        db.session.query(MessageLog.user_message)
        .filter(MessageLog.dialog_id == Dialog.id)
        .order_by(MessageLog.message_index.asc())
        .limit(1)
        .correlate(Dialog)
        .scalar_subquery()
    )
    dialog_rows = (
        db.session.query(
            Dialog.id.label("dialog_id"),
            Dialog.is_active,
            User.username,
            User.telegram_id,
            func.coalesce(message_stats.c.message_count, 0).label("message_count"),
            func.coalesce(message_stats.c.tokens_spent, 0).label("tokens_spent"),
            func.coalesce(message_stats.c.prompt_tokens_spent, 0).label("prompt_tokens_spent"),
            func.coalesce(message_stats.c.completion_tokens_spent, 0).label("completion_tokens_spent"),
            first_message_subquery.label("first_message"),
        )
        .join(User, Dialog.user_id == User.id)
        .outerjoin(message_stats, message_stats.c.dialog_id == Dialog.id)
        .order_by(Dialog.started_at.desc())
        .limit(dialog_limit)
        .all()
    )
    dialog_logs: List[Dict[str, Any]] = []
    for row in dialog_rows:
        base_title = row.first_message or ""
        title = base_title[:15]
        if base_title and len(base_title) > 15:
            title = f"{title}…"
        if not title:
            title = f"Диалог #{row.dialog_id}"
        login = row.username or row.telegram_id or "—"
        dialog_logs.append(
            {
                "id": row.dialog_id,
                "title": title,
                "full_title": base_title,
                "message_count": int(row.message_count or 0),
                "tokens_spent": int(row.tokens_spent or 0),
                "input_tokens": int(row.prompt_tokens_spent or 0),
                "output_tokens": int(row.completion_tokens_spent or 0),
                "username": login,
                "is_active": row.is_active,
            }
        )
    # NOTE[agent]: Функция формирует краткое представление текста для таблицы логов.
    def _make_preview(text: Optional[str]) -> Tuple[str, bool, bool, str]:
        """Возвращает укороченную версию текста и метаданные для отображения."""

        if not text:
            return "—", False, False, ""
        preview_limit = 150
        is_long = len(text) > preview_limit
        preview = text if not is_long else f"{text[:preview_limit]}..."
        return preview, True, is_long, text

    records = (
        MessageLog.query.order_by(MessageLog.created_at.desc())
        .limit(limit)
        .all()
    )

    message_rows: List[Dict[str, Any]] = []
    for record in records:
        user_preview, has_user_text, user_truncated, user_full = _make_preview(record.user_message)
        llm_preview, has_llm_text, llm_truncated, llm_full = _make_preview(record.llm_response)
        created_at_value = record.created_at
        created_at_formatted = "—"
        if isinstance(created_at_value, datetime):
            created_at_formatted = created_at_value.strftime("%d.%m.%Y")
        message_rows.append(
            {
                "id": record.id,
                "dialog_id": record.dialog_id,
                "message_index": int(record.message_index or 0),
                "username": record.user.username or record.user.telegram_id or "—",
                "user_message_preview": user_preview,
                "user_message_full": user_full,
                "user_message_present": has_user_text,
                "user_message_truncated": user_truncated,
                "llm_response_preview": llm_preview,
                "llm_response_full": llm_full,
                "llm_response_present": has_llm_text,
                "llm_response_truncated": llm_truncated,
                "tokens_used": int(record.tokens_used or 0),
                "input_tokens": int(record.prompt_tokens or 0),
                "output_tokens": int(record.completion_tokens or 0),
                "created_at": created_at_formatted,
            }
        )
    return render_template(
        "admin/logs.html",
        message_rows=message_rows,
        limit=limit,
        dialog_logs=dialog_logs,
        dialog_limit=dialog_limit,
    )


# NOTE[agent]: Управление поставщиками LLM и их API-ключами.
@admin_bp.route("/providers", methods=["GET", "POST"])
def manage_providers() -> Union[Response, str]:
    """Позволяет добавлять и редактировать поставщиков API."""

    vendor_choices = list(LLMProvider.allowed_vendors())
    allowed_vendors = set(vendor_choices)
    vendor_titles = LLMProvider.vendor_titles()

    if request.method == "POST":
        action = request.form.get("action", "create")
        vendor = (request.form.get("vendor", "") or "").strip().lower()
        name = request.form.get("name", "").strip()
        api_key = request.form.get("api_key", "").strip()

        if action == "create":
            if vendor not in allowed_vendors:
                current_app.logger.warning("Не удалось создать провайдера: неизвестный тип %s", vendor)
            else:
                provider_name = name or vendor_titles.get(vendor, vendor.title())
                provider = LLMProvider(name=provider_name, vendor=vendor, api_key=api_key)
                db.session.add(provider)
                db.session.commit()
        elif action == "update":
            provider_id_raw = request.form.get("provider_id")
            try:
                provider_id = int(provider_id_raw) if provider_id_raw else None
            except (TypeError, ValueError):
                provider_id = None
            provider = LLMProvider.query.get(provider_id) if provider_id is not None else None
            if not provider:
                current_app.logger.warning("Не удалось обновить провайдера: id=%s не найден", provider_id_raw)
            else:
                if vendor and vendor in allowed_vendors:
                    provider.vendor = vendor
                elif vendor:
                    current_app.logger.warning("Игнорируем неизвестный тип провайдера: %s", vendor)
                new_name = name or provider.name
                provider.update_credentials(name=new_name, api_key=api_key)
                db.session.commit()

    providers = LLMProvider.query.order_by(LLMProvider.created_at.desc()).all()
    return render_template(
        "admin/providers.html",
        providers=providers,
        vendor_titles=vendor_titles,
        vendor_choices=vendor_choices,
    )


# NOTE[agent]: Управление конфигурациями моделей и выбор активной.
@admin_bp.route("/models", methods=["GET", "POST"])
def manage_models() -> Union[Response, str]:
    """Позволяет добавлять новые модели и выбирать активную."""

    settings_service = SettingsService()
    if request.method == "POST":
        action = request.form.get("action", "create")
        name = request.form.get("name", "").strip()
        model_name = request.form.get("model", "").strip()
        instruction = request.form.get("system_instruction", "").strip() or None

        # NOTE[agent]: Вспомогательная функция безопасно преобразует значение в float.
        def _float(field: str, default: float) -> float:
            """Возвращает значение поля как float или значение по умолчанию."""

            value = request.form.get(field, "")
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        # NOTE[agent]: Вспомогательная функция безопасно преобразует значение в int.
        def _int(field: str, default: int) -> int:
            """Возвращает значение поля как int или значение по умолчанию."""

            value = request.form.get(field, "")
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        temperature = _float("temperature", 1.0)
        max_tokens = _int("max_tokens", 512)
        dialog_token_limit = _int("dialog_token_limit", 20000)
        top_p = _float("top_p", 1.0)
        is_default = request.form.get("is_default") == "on"
        provider_id_raw = request.form.get("provider_id")
        provider: Optional[LLMProvider] = None
        try:
            provider_id = int(provider_id_raw) if provider_id_raw else None
        except (TypeError, ValueError):
            provider_id = None
        if provider_id is not None:
            provider = LLMProvider.query.get(provider_id)
            if provider is None:
                current_app.logger.warning("Поставщик с id=%s не найден", provider_id)

        if action == "create" and name and model_name and provider:
            if is_default:
                ModelConfig.query.update({ModelConfig.is_default: False})
            model = ModelConfig(
                name=name,
                model=model_name,
                provider=provider,
                temperature=temperature,
                max_tokens=max_tokens,
                dialog_token_limit=dialog_token_limit,
                top_p=top_p,
                system_instruction=instruction,
                is_default=is_default,
            )
            db.session.add(model)
            db.session.commit()
            if is_default:
                settings_service.set("active_model_id", str(model.id))
        elif action == "create" and not provider:
            current_app.logger.warning("Не удалось создать модель %s: не выбран поставщик", name)
        elif action == "update":
            model_id_raw = request.form.get("model_id")
            model_obj: Optional[ModelConfig] = None
            try:
                model_id = int(model_id_raw) if model_id_raw else None
            except (TypeError, ValueError):
                model_id = None
            if model_id is not None:
                model_obj = ModelConfig.query.get(model_id)
            if model_obj:
                model_obj.name = name or model_obj.name
                model_obj.model = model_name or model_obj.model
                if provider:
                    model_obj.provider = provider
                model_obj.temperature = temperature
                model_obj.max_tokens = max_tokens
                model_obj.dialog_token_limit = dialog_token_limit
                model_obj.top_p = top_p
                model_obj.system_instruction = instruction
                if is_default:
                    ModelConfig.query.update({ModelConfig.is_default: False})
                    model_obj.is_default = True
                else:
                    model_obj.is_default = False
                db.session.commit()
                if is_default:
                    settings_service.set("active_model_id", str(model_obj.id))
                else:
                    current_active = settings_service.get("active_model_id")
                    if current_active and current_active == str(model_obj.id):
                        settings_service.set("active_model_id", "")
    models = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    providers = LLMProvider.query.order_by(LLMProvider.name.asc()).all()
    provider_titles = LLMProvider.vendor_titles()
    active_model_id = settings_service.get("active_model_id")
    return render_template(
        "admin/models.html",
        models=models,
        active_model_id=active_model_id,
        providers=providers,
        provider_titles=provider_titles,
    )


# NOTE[agent]: Настройки API-ключей и параметров интеграции.
@admin_bp.route("/settings", methods=["GET", "POST"])
def manage_settings() -> Union[Response, str]:
    """Позволяет обновить интеграционные настройки системы."""

    settings_service = SettingsService()
    keys = [
        "telegram_bot_token",
        "webhook_url",
        "webhook_secret",
        "default_mode",
        "dialog_token_limit",
    ]
    if request.method == "POST":
        for key in keys:
            settings_service.set(key, request.form.get(key, ""))
        active_model = request.form.get("active_model_id")
        if active_model:
            settings_service.set("active_model_id", active_model)
        return redirect(url_for("admin.manage_settings"))
    settings = settings_service.all_settings()
    models = ModelConfig.query.order_by(ModelConfig.name.asc()).all()
    return render_template("admin/settings.html", settings=settings, models=models)


# NOTE[agent]: Управление пользовательскими командами Telegram-бота.
@admin_bp.route("/commands", methods=["GET", "POST"])
def manage_commands() -> Union[Response, str]:
    """Позволяет добавить или отредактировать команды вида '/example'."""

    if request.method == "POST":
        action = request.form.get("action", "create")
        command_raw = (request.form.get("command", "") or "").strip()
        response_text = (request.form.get("response", "") or "").strip()
        normalized = command_raw.lstrip("/")
        if " " in normalized:
            normalized = normalized.split()[0]
        normalized = normalized.lower()

        if action == "delete":
            command_id_raw = request.form.get("command_id")
            try:
                command_id = int(command_id_raw) if command_id_raw else None
            except (TypeError, ValueError):
                command_id = None
            command = None
            if command_id is not None:
                try:
                    command = BotCommand.query.get(command_id)
                except SQLAlchemyError as exc:
                    current_app.logger.warning("Ошибка при поиске команды: %s", exc)
                    db.session.rollback()
            if command:
                try:
                    db.session.delete(command)
                    db.session.commit()
                except SQLAlchemyError as exc:
                    db.session.rollback()
                    current_app.logger.warning("Не удалось удалить команду %s: %s", command_id_raw, exc)
            else:
                current_app.logger.warning("Не удалось удалить команду: id=%s", command_id_raw)
            return redirect(url_for("admin.manage_commands"))

        if not normalized:
            current_app.logger.warning("Команда не указана или указана некорректно")
        elif not response_text:
            current_app.logger.warning("Не задан ответ для команды %s", command_raw)
        else:
            try:
                existing = BotCommand.query.filter_by(name=normalized).first()
            except SQLAlchemyError as exc:
                existing = None
                current_app.logger.warning("Ошибка при поиске команды %s: %s", normalized, exc)
                db.session.rollback()
            if action == "update":
                command_id_raw = request.form.get("command_id")
                try:
                    command_id = int(command_id_raw) if command_id_raw else None
                except (TypeError, ValueError):
                    command_id = None
                command = None
                if command_id is not None:
                    try:
                        command = BotCommand.query.get(command_id)
                    except SQLAlchemyError as exc:
                        current_app.logger.warning(
                            "Ошибка при загрузке команды id=%s: %s", command_id_raw, exc
                        )
                        db.session.rollback()
                if not command:
                    current_app.logger.warning(
                        "Не удалось обновить команду: id=%s не найден", command_id_raw
                    )
                else:
                    conflict = None
                    if existing and existing.id != command.id:
                        conflict = existing
                    if conflict:
                        current_app.logger.warning(
                            "Конфликт имён команд: %s уже используется", normalized
                        )
                    else:
                        try:
                            command.update(name=normalized, response_text=response_text)
                            db.session.commit()
                        except SQLAlchemyError as exc:
                            db.session.rollback()
                            current_app.logger.warning(
                                "Ошибка при обновлении команды %s: %s", normalized, exc
                            )
                        return redirect(url_for("admin.manage_commands"))
            else:
                if existing:
                    try:
                        existing.update(response_text=response_text)
                        db.session.commit()
                    except SQLAlchemyError as exc:
                        db.session.rollback()
                        current_app.logger.warning(
                            "Ошибка при обновлении ответа команды %s: %s", normalized, exc
                        )
                else:
                    try:
                        command = BotCommand(name=normalized, response_text=response_text)
                        db.session.add(command)
                        db.session.commit()
                    except SQLAlchemyError as exc:
                        db.session.rollback()
                        current_app.logger.warning(
                            "Ошибка при создании команды %s: %s", normalized, exc
                        )
                return redirect(url_for("admin.manage_commands"))

    try:
        commands = BotCommand.query.order_by(BotCommand.name.asc()).all()
    except SQLAlchemyError as exc:
        current_app.logger.warning("Ошибка при загрузке списка команд: %s", exc)
        db.session.rollback()
        commands = []
    return render_template("admin/commands.html", commands=commands)


# NOTE[agent]: API для получения всех настроек в JSON.
@admin_bp.route("/api/settings", methods=["GET", "POST"])
def api_settings() -> Response:
    """Возвращает или обновляет настройки через JSON API."""

    settings_service = SettingsService()
    if request.method == "GET":
        return jsonify(settings_service.all_settings())
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    for key, value in payload.items():
        settings_service.set(key, value)
    return jsonify({"status": "ok"})


# NOTE[agent]: API-метод запуска бота в режиме polling.
@admin_bp.route("/api/bot/start-polling", methods=["POST"])
def api_start_polling() -> Response:
    """Запускает бота в режиме polling."""

    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    try:
        bot_manager.start_polling()
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.exception("Не удалось запустить polling")
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({"status": "ok"})


# NOTE[agent]: API-метод запуска webhook.
@admin_bp.route("/api/bot/start-webhook", methods=["POST"])
def api_start_webhook() -> Response:
    """Устанавливает webhook для Telegram."""

    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    try:
        url = bot_manager.start_webhook()
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.exception("Не удалось установить webhook")
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({"status": "ok", "webhook_url": url})


# NOTE[agent]: API-метод остановки бота.
@admin_bp.route("/api/bot/stop", methods=["POST"])
def api_stop_bot() -> Response:
    """Останавливает polling Telegram-бота."""

    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    bot_manager.stop()
    return jsonify({"status": "ok"})


# NOTE[agent]: Обработчик входящих webhook-запросов от Telegram.
@admin_bp.route("/bot/webhook", methods=["POST"])
def telegram_webhook() -> Response:
    """Принимает webhook и передаёт обновление менеджеру бота."""

    bot_manager: Optional[TelegramBotManager] = current_app.extensions.get("bot_manager")  # type: ignore[assignment]
    if not bot_manager:
        return jsonify({"status": "error", "message": "Bot manager is not configured"}), 500
    payload = request.get_json(force=True)
    bot_manager.process_webhook_update(payload)
    return jsonify({"status": "received"})


# NOTE[agent]: Маршрут завершает диалог пользователя из админки.
@admin_bp.route("/dialogs/<int:dialog_id>/close", methods=["POST"])
def close_dialog(dialog_id: int) -> Response:
    """Помечает диалог закрытым."""

    dialog = Dialog.query.get_or_404(dialog_id)
    dialog.close()
    db.session.commit()
    return redirect(url_for("admin.logs"))
