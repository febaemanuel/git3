"""Application package.

During the modular refactor, ``app/main.py`` still holds the legacy monolithic
Flask app. This ``__init__`` re-exports everything from there so existing
imports like ``from app import db, Campanha, WhatsApp`` keep working
unchanged. ``create_app()`` is currently a thin shim that returns the legacy
app; later phases will replace it with a proper factory that registers
blueprints.
"""

from app.main import *  # noqa: F401,F403  (re-export legacy module surface)
from app.main import app as _legacy_app


def create_app(config_name=None):
    """Application factory skeleton.

    For now this returns the already-built legacy ``app`` instance so callers
    that move to ``from app import create_app`` keep getting a fully wired
    Flask app. F4/F5 will turn this into a real factory (config selection,
    extension binding, blueprint registration).
    """
    return _legacy_app
