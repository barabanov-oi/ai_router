"""Точка входа для запуска Flask-приложения."""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
