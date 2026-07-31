"""Clients tasks package — re-exports all task functions for backwards compatibility."""
from ._utils import is_celery_enabled, run_task
from .notifications import (
    send_weekly_reminders, check_inactive_clients, send_booking_reminders,
    check_expiring_packages, send_upcoming_event_reminders, send_custom_campaign,
    cleanup_old_notifications, send_assessment_notification_task,
    flush_notification_group, send_booking_confirmation_task,
)
from .email import send_bulk_email_task
from .stripe import STRIPE_ALERT_RECIPIENT, check_stripe_health
from .referrals import grant_referral_reward, expire_stale_referrals
from .select import send_game_day_digest

__all__ = [
    'is_celery_enabled',
    'run_task',
    'send_weekly_reminders',
    'check_inactive_clients',
    'send_booking_reminders',
    'check_expiring_packages',
    'send_upcoming_event_reminders',
    'send_custom_campaign',
    'cleanup_old_notifications',
    'send_assessment_notification_task',
    'flush_notification_group',
    'send_booking_confirmation_task',
    'send_bulk_email_task',
    'STRIPE_ALERT_RECIPIENT',
    'check_stripe_health',
    'grant_referral_reward',
    'expire_stale_referrals',
    'send_game_day_digest',
]
