"""Config classes loaded from environment variables."""

import os


# Project root (parent of the ``app`` package).
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


class BaseConfig:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'busca-ativa-huwc-2024-secret')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DATABASE_URL') or 'sqlite:///busca_ativa.db'
    )


class DevConfig(BaseConfig):
    DEBUG = True


class ProdConfig(BaseConfig):
    DEBUG = False


CONFIG_MAP = {
    'dev': DevConfig,
    'development': DevConfig,
    'prod': ProdConfig,
    'production': ProdConfig,
}


def get_config(name=None):
    """Pick a config class based on ``name`` or ``FLASK_ENV``/``APP_ENV``."""
    if name is None:
        name = (
            os.environ.get('FLASK_ENV')
            or os.environ.get('APP_ENV')
            or 'dev'
        )
    return CONFIG_MAP.get(name.lower(), DevConfig)
