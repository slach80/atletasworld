"""
Django settings for Atletas Performance Center project.
"""
import os
from pathlib import Path
import environ

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Environment variables
env = environ.Env(
    DEBUG=(bool, False)
)
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# Security
SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# Application definition
INSTALLED_APPS = [
    # Grappelli must come before django.contrib.admin
    'grappelli',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third party
    'rest_framework',
    'corsheaders',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.apple',
    'allauth.socialaccount.providers.twitter_oauth2',
    'allauth.socialaccount.providers.facebook',
    'allauth.socialaccount.providers.instagram',
    'django.contrib.sites',

    # UI packages
    'crispy_forms',
    'crispy_bootstrap5',
    'django_bootstrap5',

    # Celery
    'django_celery_beat',
    'django_celery_results',

    # Local apps
    'clients.apps.ClientsConfig',
    'coaches',
    'bookings',
    'payments',
    'analytics',
    'reviews',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'atletasworld.middleware.SecurityHeadersMiddleware',
    'atletasworld.middleware.PasswordExpiryMiddleware',
]

ROOT_URLCONF = 'atletasworld.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'atletasworld.context_processors.pending_field_rentals',
            ],
        },
    },
]

WSGI_APPLICATION = 'atletasworld.wsgi.application'

# Database
DATABASES = {
    'default': env.db('DATABASE_URL', default='sqlite:///db.sqlite3')
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 12},
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Chicago'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Stripe
STRIPE_PUBLIC_KEY = env('STRIPE_PUBLIC_KEY', default='')
STRIPE_SECRET_KEY = env('STRIPE_SECRET_KEY', default='')
STRIPE_WEBHOOK_SECRET = env('STRIPE_WEBHOOK_SECRET', default='')  # Required in production

# Tax rate (0.00–1.00, e.g. 0.07 = 7%). Set to 0 to disable.
TAX_RATE = env.float('TAX_RATE', default=0.0)

# Email
EMAIL_BACKEND        = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
# SMTP settings (used when EMAIL_BACKEND is django.core.mail.backends.smtp.EmailBackend)
EMAIL_HOST           = env('EMAIL_HOST',          default='smtp.gmail.com')
EMAIL_PORT           = env.int('EMAIL_PORT',      default=587)
EMAIL_USE_TLS        = env.bool('EMAIL_USE_TLS',  default=True)
EMAIL_HOST_USER      = env('EMAIL_HOST_USER',     default='')
EMAIL_HOST_PASSWORD  = env('EMAIL_HOST_PASSWORD', default='')

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/hour',
        'user': '300/hour',
    },
}

# CORS
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])

# Sites framework
SITE_ID = 1

# Authentication
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Allauth settings
ACCOUNT_ADAPTER = 'atletasworld.adapters.SilentAuthAdapter'
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_LOGOUT_ON_GET = True
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'optional'
LOGIN_REDIRECT_URL = '/login-redirect/'
LOGOUT_REDIRECT_URL = '/'

# Social account settings
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'APP': {
            'client_id': env('GOOGLE_CLIENT_ID', default=''),
            'secret': env('GOOGLE_CLIENT_SECRET', default=''),
        }
    },
    'apple': {
        'APP': {
            'client_id': env('APPLE_CLIENT_ID', default=''),
            'secret': env('APPLE_CLIENT_SECRET', default=''),
            'key': env('APPLE_KEY_ID', default=''),
            'certificate_key': env('APPLE_PRIVATE_KEY', default=''),
        }
    },
    'twitter_oauth2': {
        'APP': {
            'client_id': env('TWITTER_CLIENT_ID', default=''),
            'secret': env('TWITTER_CLIENT_SECRET', default=''),
        }
    },
    'facebook': {
        'METHOD': 'oauth2',
        'SCOPE': ['email', 'public_profile'],
        'AUTH_PARAMS': {'auth_type': 'reauthenticate'},
        'FIELDS': ['id', 'email', 'name', 'first_name', 'last_name'],
        'APP': {
            'client_id': env('FACEBOOK_APP_ID', default=''),
            'secret': env('FACEBOOK_APP_SECRET', default=''),
        }
    },
    'instagram': {
        'APP': {
            'client_id': env('INSTAGRAM_CLIENT_ID', default=''),
            'secret': env('INSTAGRAM_CLIENT_SECRET', default=''),
        }
    },
}

# Crispy Forms settings
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# Django Bootstrap5 settings
BOOTSTRAP5 = {
    'css_url': {
        'url': 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
        'integrity': 'sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN',
        'crossorigin': 'anonymous',
    },
    'javascript_url': {
        'url': 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js',
        'integrity': 'sha384-C6RzsynM9kWDrMNeT87bh95OGNyZPhcTNXj1NW7RuBCsyN/o0jlpcV8Qyq46cDfL',
        'crossorigin': 'anonymous',
    },
    'theme_url': None,
    'color_mode': None,
}

# Grappelli settings
GRAPPELLI_ADMIN_TITLE = 'Atletas Performance Center Admin'
GRAPPELLI_AUTOCOMPLETE_LIMIT = 10

# =============================================================================
# NOTIFICATION SERVICES - Feature Flags (all paid services disabled by default)
# =============================================================================
# Set to True in .env to enable paid services

# SMS via Twilio (PAID - ~$0.0075/SMS)
SMS_ENABLED = env.bool('SMS_ENABLED', default=False)
TWILIO_ACCOUNT_SID = env('TWILIO_ACCOUNT_SID', default='')
TWILIO_AUTH_TOKEN = env('TWILIO_AUTH_TOKEN', default='')
TWILIO_PHONE_NUMBER = env('TWILIO_PHONE_NUMBER', default='')

# Web Push Notifications (FREE - uses VAPID)
PUSH_NOTIFICATIONS_ENABLED = env.bool('PUSH_NOTIFICATIONS_ENABLED', default=False)
VAPID_PUBLIC_KEY = env('VAPID_PUBLIC_KEY', default='')
VAPID_PRIVATE_KEY = env('VAPID_PRIVATE_KEY', default='')

# Production Email via SendGrid/Mailgun (PAID)
# Default uses Django console backend (FREE for development)
PRODUCTION_EMAIL_ENABLED = env.bool('PRODUCTION_EMAIL_ENABLED', default=False)

# Celery for background tasks (requires Redis - FREE locally, paid in cloud)
CELERY_ENABLED = env.bool('CELERY_ENABLED', default=False)
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='django-db')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# =============================================================================
# General Settings
# =============================================================================
SITE_URL = env('SITE_URL', default='http://localhost:8000')
# Delay (seconds) between each email in a bulk send — prevents Gmail rate-limit lockdowns
BULK_EMAIL_SEND_DELAY = env.float('BULK_EMAIL_SEND_DELAY', default=0.5)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@atletasperformancecenter.com')
SERVER_EMAIL = env('SERVER_EMAIL', default='noreply@atletasperformancecenter.com')

# =============================================================================
# Security hardening (production)
# =============================================================================
SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 31536000          # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False  # Must be False — JS needs to read csrftoken for AJAX requests

CSRF_TRUSTED_ORIGINS = env.list(
    'CSRF_TRUSTED_ORIGINS',
    default=['https://atletasperformancecenter.com', 'https://www.atletasperformancecenter.com']
)
