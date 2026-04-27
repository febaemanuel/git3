"""Defensive Celery imports.

Yields ``celery_app`` and ``AsyncResult`` if Celery is installed, else
``None`` for both — letting routes degrade gracefully when running tests
or one-off scripts without a broker.
"""

import logging


logger = logging.getLogger(__name__)


try:
    from celery_app import celery as celery_app
    from celery.result import AsyncResult
except ImportError as e:
    celery_app = None
    AsyncResult = None
    logger.warning(
        f"Celery não disponível - funcionalidades assíncronas desabilitadas: {e}"
    )
