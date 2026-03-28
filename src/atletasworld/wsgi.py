"""
WSGI config for Atletas Performance Center project.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'atletasworld.settings')
application = get_wsgi_application()
