"""Модели базы данных приложения."""

from flask_sqlalchemy import SQLAlchemy

# NOTE[agent]: Экземпляр SQLAlchemy используется всеми моделями.
db = SQLAlchemy()

# NOTE[agent]: Импорты моделей размещаются в конце файла, чтобы избежать циклов.
from .user import User  # noqa: E402  pylint: disable=wrong-import-position
from .dialog import Dialog  # noqa: E402  pylint: disable=wrong-import-position
from .message import MessageLog  # noqa: E402  pylint: disable=wrong-import-position
from .model_config import ModelConfig  # noqa: E402  pylint: disable=wrong-import-position
from .provider import LLMProvider  # noqa: E402  pylint: disable=wrong-import-position
from .setting import AppSetting  # noqa: E402  pylint: disable=wrong-import-position
