"""Точка входа для запуска Flask-приложения."""

from __future__ import annotations

from app import create_app


# NOTE[agent]: Создание экземпляра приложения для WSGI/CLI запуска.
app = create_app()


# NOTE[agent]: Позволяет запускать приложение через `python run.py`.
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
