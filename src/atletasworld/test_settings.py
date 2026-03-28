"""
Test settings for Atletas Performance Center.
"""
from .settings import *

# Use SQLite for testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Disable Celery for testing
CELERY_ENABLED = False
CELERY_BROKER_URL = None

# Disable email sending
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Disable feature flags for paid services
SMS_ENABLED = False
PUSH_NOTIFICATIONS_ENABLED = False
PRODUCTION_EMAIL_ENABLED = False

# Use console password hasher for faster tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Speed up tests
DEBUG = False

# Secret key for testing
SECRET_KEY = 'test-secret-key-not-for-production'

# Disable migrations for faster tests (optional)
# class DisableMigrations:
#     def __contains__(self, item):
#         return True
#     def __getitem__(self, item):
#         return None
# MIGRATION_MODULES = DisableMigrations()
