"""Blueprint declaration for the administrative web interface."""

from flask import Blueprint

# NOTE(agents): admin_bp groups all routes under the /admin prefix for clarity.
admin_bp = Blueprint("admin", __name__, template_folder="templates", static_folder="static")
