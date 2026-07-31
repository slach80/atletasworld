"""
Celery task utilities — helpers shared across task modules.
"""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def is_celery_enabled():
    """Check if Celery is enabled in settings."""
    return getattr(settings, 'CELERY_ENABLED', False)


def run_task(task_func, *args, **kwargs):
    """
    Run a Celery task either async (if enabled) or sync (if disabled).

    Usage:
        run_task(send_booking_confirmation_task, booking_id=123)
    """
    if is_celery_enabled():
        # Run asynchronously via Celery
        return task_func.delay(*args, **kwargs)
    else:
        # Run synchronously (no Celery worker needed)
        logger.info(f"Celery disabled, running {task_func.__name__} synchronously")
        return task_func(*args, **kwargs)
