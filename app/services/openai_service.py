"""Service providing high level helpers to talk to OpenAI models."""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import openai  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    openai = None  # type: ignore

from app import db
from app.models import ChatMessage, User
from . import dialog_service, settings_service


class OpenAIServiceError(Exception):
    """Raised when OpenAI API cannot be reached or returns an error."""


# NOTE(agents): _build_client lazily instantiates the OpenAI client to honour runtime configuration changes.
def _build_client(api_key: str) -> Tuple[str, object]:
    """Return a tuple describing the available OpenAI client implementation."""

    if OpenAI is not None:
        return "new", OpenAI(api_key=api_key)
    if openai is not None:
        openai.api_key = api_key
        return "legacy", openai
    raise OpenAIServiceError("openai package is not installed")


# NOTE(agents): _call_chat_completion isolates the HTTP interaction and returns both text and usage statistics.
def _call_chat_completion(client_type: str, client: object, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> Tuple[str, Dict[str, int]]:
    """Execute a chat completion request and return the text together with usage data."""

    try:
        if client_type == "new":
            response = client.chat.completions.create(  # type: ignore[attr-defined]
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            choice = response.choices[0]
            content = choice.message.content or ""
            usage_source = response.usage
        else:
            response = client.ChatCompletion.create(  # type: ignore[attr-defined]
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            choice = response["choices"][0]
            content = choice["message"]["content"]
            usage_source = response.get("usage", {})
    except Exception as exc:  # noqa: BLE001
        logging.exception("OpenAI chat completion failed: %s", exc)
        raise OpenAIServiceError(str(exc)) from exc
    usage = {
        "prompt_tokens": getattr(usage_source, "prompt_tokens", 0) if client_type == "new" else usage_source.get("prompt_tokens", 0),
        "completion_tokens": getattr(usage_source, "completion_tokens", 0) if client_type == "new" else usage_source.get("completion_tokens", 0),
        "total_tokens": getattr(usage_source, "total_tokens", 0) if client_type == "new" else usage_source.get("total_tokens", 0),
    }
    return content, usage


# NOTE(agents): send_user_message orchestrates dialog handling, API calls and persistence for the bot workflow.
def send_user_message(user: User, message_text: str) -> str:
    """Send user message to OpenAI and persist logs, returning assistant response text."""

    config = settings_service.get_openai_configuration()
    api_key = config.get("api_key")
    if not api_key:
        raise OpenAIServiceError("OpenAI API key is not configured")
    client_type, client = _build_client(api_key)
    session = dialog_service.ensure_active_session(user, user.current_mode)
    history = dialog_service.load_history(session)
    history = dialog_service.append_message(history, "user", message_text)
    try:
        assistant_text, usage = _call_chat_completion(
            client_type,
            client,
            history,
            config["model"],
            config["temperature"],
            config["max_tokens"],
        )
    except OpenAIServiceError:
        dialog_service.save_history(session, history)
        raise
    history = dialog_service.append_message(history, "assistant", assistant_text)
    dialog_service.save_history(session, history)

    message_log = ChatMessage(
        user_id=user.id,
        session_id=session.id,
        user_message=message_text,
        assistant_message=assistant_text,
        model=config["model"],
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        total_tokens=usage["total_tokens"],
    )
    db.session.add(message_log)
    db.session.commit()
    return assistant_text
