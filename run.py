"""Entry point for launching the ai_router Flask application."""

from __future__ import annotations

from app import create_app


# NOTE(agents): The module-level application allows ``flask run`` to auto-detect the app factory.
app = create_app()


if __name__ == "__main__":
    # NOTE(agents): Running via python run.py starts the development server.
    app.run(host="0.0.0.0", port=5000)
