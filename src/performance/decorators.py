"""
Decorators for VALD performance views.
"""
from functools import wraps
from django.conf import settings
from django.http import Http404


def require_vald_enabled(view_func):
    """
    Decorator to enforce VALD_SYNC_ENABLED feature flag.

    Returns 404 if VALD integration is disabled in settings.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not settings.VALD_SYNC_ENABLED:
            raise Http404("VALD integration is not enabled")
        return view_func(request, *args, **kwargs)
    return wrapper
