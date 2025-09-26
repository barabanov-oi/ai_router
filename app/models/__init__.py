"""Модели базы данных приложения."""

from sqlalchemy import MetaData
from flask_sqlalchemy import SQLAlchemy

# NOTE[agent]: Чтобы Alembic всегда генерил имена ограничений/индексов предсказуемо
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s__%(column_0_name)s",
    "ck": "ck_%(table_name)s__%(constraint_name)s",
    "fk": "fk_%(table_name)s__%(column_0_name)s__%(referred_table_name)s__%(referred_column_0_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=convention)
# NOTE[agent]: Экземпляр SQLAlchemy используется всеми моделями.
db = SQLAlchemy()

# NOTE[agent]: Импорты моделей размещаются в конце файла, чтобы избежать циклов.
from .user import User  # noqa: E402  pylint: disable=wrong-import-position
from .dialog import Dialog  # noqa: E402  pylint: disable=wrong-import-position
from .message import MessageLog  # noqa: E402  pylint: disable=wrong-import-position
from .model_config import ModelConfig  # noqa: E402  pylint: disable=wrong-import-position
from .provider import LLMProvider  # noqa: E402  pylint: disable=wrong-import-position
from .setting import AppSetting  # noqa: E402  pylint: disable=wrong-import-position
from .command import BotCommand  # noqa: E402  pylint: disable=wrong-import-position
