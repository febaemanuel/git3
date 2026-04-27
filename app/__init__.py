"""Application package + factory.

``create_app()`` is the canonical entry point used by ``wsgi.py``. The
package also exposes ``app`` lazily (via module ``__getattr__``) so legacy
callers like ``tasks.py`` and ``migrate_config_geral.py`` that import
``from app import app`` keep working without forcing eager construction at
import time.

A few extension instances (``db``, ``csrf``, ``login_manager``) are re-
exported here for the same backwards-compat reason; new code should prefer
``from app.extensions import db``.
"""

import os

from app.extensions import csrf, db, login_manager  # re-exported


_app_instance = None


def create_app(config_name=None):
    """Build the Flask app, register extensions and blueprints, return it.

    Idempotent: subsequent calls return the same instance.
    """
    global _app_instance
    if _app_instance is not None:
        return _app_instance

    # dotenv if available — must run before reading config so DATABASE_URL etc
    # are picked up.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Importing app.main runs the (now app-free) module-level setup: logging,
    # constants, helpers, AI/OCR classes, the @login_manager.user_loader, etc.
    from app import main as _main
    from app.config import BASE_DIR, BaseConfig
    from flask import Flask

    static_dir = os.path.join(BASE_DIR, 'static')
    # template_folder defaults to <package>/templates (i.e. app/templates).
    flask_app = Flask(
        'app',
        static_folder=static_dir if os.path.isdir(static_dir) else None,
    )
    flask_app.config.from_object(BaseConfig)
    os.makedirs(flask_app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(flask_app)
    csrf.init_app(flask_app)
    login_manager.init_app(flask_app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Faca login para acessar.'
    login_manager.login_message_category = 'warning'

    @flask_app.context_processor
    def _inject_dashboard_route():
        return dict(get_dashboard_route=_main.get_dashboard_route)

    @flask_app.cli.command('init-db')
    def _init_db_cli():
        db.create_all()
        _main.criar_admin()
        print(f"DB criado! Admin: {_main.ADMIN_EMAIL} / {_main.ADMIN_SENHA}")

    from app.routes import register_blueprints
    register_blueprints(flask_app)

    with flask_app.app_context():
        db.create_all()
        _main.criar_admin()
        _main.criar_faqs_padrao()
        _main.criar_tutoriais_padrao()

    _app_instance = flask_app
    return flask_app


def __getattr__(name):
    """Lazy attribute access: ``from app import app`` builds the singleton on
    first access without forcing eager construction at package import."""
    if name == 'app':
        return create_app()
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
