"""
Celery configuration for Atletas World.
"""
import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'atletasworld.settings')

app = Celery('atletasworld')

# Load config from Django settings with CELERY_ namespace
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# Celery Beat Schedule - Automated notification tasks
app.conf.beat_schedule = {
    # Weekly session reminder - Every Monday at 9 AM
    'weekly-session-reminder': {
        'task': 'clients.tasks.send_weekly_reminders',
        'schedule': crontab(hour=9, minute=0, day_of_week=1),
        'options': {'queue': 'notifications'},
    },

    # Check inactive clients - Every day at 10 AM
    'inactive-client-check': {
        'task': 'clients.tasks.check_inactive_clients',
        'schedule': crontab(hour=10, minute=0),
        'options': {'queue': 'notifications'},
    },

    # Booking reminders - Every day at 8 AM (24 hours before)
    'booking-reminders': {
        'task': 'clients.tasks.send_booking_reminders',
        'schedule': crontab(hour=8, minute=0),
        'options': {'queue': 'notifications'},
    },

    # Package expiring reminders - Every day at 9 AM
    'package-expiring-check': {
        'task': 'clients.tasks.check_expiring_packages',
        'schedule': crontab(hour=9, minute=0),
        'options': {'queue': 'notifications'},
    },

    # Upcoming events reminder - Every day at 8 AM
    'upcoming-events-reminder': {
        'task': 'clients.tasks.send_upcoming_event_reminders',
        'schedule': crontab(hour=8, minute=0),
        'options': {'queue': 'notifications'},
    },

    # Clean up old notifications - Every Sunday at 2 AM
    'cleanup-old-notifications': {
        'task': 'clients.tasks.cleanup_old_notifications',
        'schedule': crontab(hour=2, minute=0, day_of_week=0),
        'options': {'queue': 'maintenance'},
    },
}

# Task routing
app.conf.task_routes = {
    'clients.tasks.*': {'queue': 'notifications'},
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
