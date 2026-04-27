"""Blueprint registration."""

from app.routes.admin import bp as admin_bp
from app.routes.api import bp as api_bp
from app.routes.auth import bp as auth_bp
from app.routes.consultas import bp as consultas_bp
from app.routes.fila import bp as fila_bp
from app.routes.geral import bp as geral_bp
from app.routes.pesquisa_publica import bp as pesquisa_publica_bp
from app.routes.webhook import bp as webhook_bp


ALL_BLUEPRINTS = (
    auth_bp,
    fila_bp,
    consultas_bp,
    geral_bp,
    pesquisa_publica_bp,
    admin_bp,
    api_bp,
    webhook_bp,
)


def register_blueprints(app):
    """Register every route blueprint on the given Flask app."""
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
