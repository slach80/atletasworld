"""
Celery tasks for automated notifications.

Note: All tasks can run synchronously when CELERY_ENABLED=False.
Use run_task() helper to automatically choose sync/async execution.
"""
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
import logging

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


@shared_task(bind=True, max_retries=3)
def send_weekly_reminders(self):
    """
    Send weekly reminders to clients who haven't booked this week.
    Runs every Monday at 9 AM.
    """
    from .models import Client, NotificationTemplate
    from .services import NotificationService
    from bookings.models import Booking

    try:
        template = NotificationTemplate.objects.get(
            template_type='weekly_reminder',
            is_active=True
        )
    except NotificationTemplate.DoesNotExist:
        logger.warning("Weekly reminder template not found or inactive")
        return "No active template"

    week_ago = timezone.now() - timedelta(days=7)
    sent_count = 0

    # Get clients who haven't booked in the past week
    active_clients = Client.objects.filter(
        user__is_active=True
    ).exclude(
        bookings__scheduled_date__gte=week_ago.date(),
        bookings__status__in=['confirmed', 'completed']
    ).distinct()

    for client in active_clients:
        try:
            # Check notification preferences
            prefs = getattr(client, 'notification_preferences', None)
            if prefs and prefs.promotional_updates == 'none':
                continue

            context = {
                'client_name': client.user.first_name or client.user.username,
                'booking_link': f"{getattr(settings, 'SITE_URL', '')}/portal/book/",
                'site_url': getattr(settings, 'SITE_URL', ''),
            }

            NotificationService.send_notification_from_template(client, template, context)
            sent_count += 1

        except Exception as e:
            logger.error(f"Failed to send weekly reminder to {client}: {e}")

    logger.info(f"Sent weekly reminders to {sent_count} clients")
    return f"Sent weekly reminders to {sent_count} clients"


@shared_task(bind=True, max_retries=3)
def check_inactive_clients(self):
    """
    Target clients who haven't booked in 3+ weeks with re-engagement campaign.
    Runs daily at 10 AM.
    """
    from .models import Client, NotificationTemplate, Notification
    from .services import NotificationService
    from bookings.models import Booking

    try:
        template = NotificationTemplate.objects.get(
            template_type='inactive_client',
            is_active=True
        )
    except NotificationTemplate.DoesNotExist:
        logger.warning("Inactive client template not found or inactive")
        return "No active template"

    three_weeks_ago = timezone.now() - timedelta(weeks=3)
    sent_count = 0

    # Get clients whose last booking was more than 3 weeks ago
    inactive_clients = Client.objects.filter(
        user__is_active=True,
        bookings__scheduled_date__lt=three_weeks_ago.date()
    ).exclude(
        bookings__scheduled_date__gte=three_weeks_ago.date()
    ).distinct()

    for client in inactive_clients:
        try:
            # Check if we've already sent an inactive notification recently
            recent_notification = Notification.objects.filter(
                client=client,
                notification_type='inactive_client',
                created_at__gte=timezone.now() - timedelta(days=14)
            ).exists()

            if recent_notification:
                continue

            # Calculate weeks inactive
            last_booking = Booking.objects.filter(
                client=client,
                status__in=['confirmed', 'completed']
            ).order_by('-scheduled_date').first()

            weeks_inactive = 3
            if last_booking:
                days_since = (timezone.now().date() - last_booking.scheduled_date).days
                weeks_inactive = days_since // 7

            context = {
                'client_name': client.user.first_name or client.user.username,
                'weeks_inactive': weeks_inactive,
                'special_offer_link': f"{getattr(settings, 'SITE_URL', '')}/portal/packages/",
                'booking_link': f"{getattr(settings, 'SITE_URL', '')}/portal/book/",
                'site_url': getattr(settings, 'SITE_URL', ''),
            }

            NotificationService.send_notification_from_template(client, template, context)
            sent_count += 1

        except Exception as e:
            logger.error(f"Failed to send inactive client notification to {client}: {e}")

    logger.info(f"Sent inactive client notifications to {sent_count} clients")
    return f"Sent inactive client notifications to {sent_count} clients"


@shared_task(bind=True, max_retries=3)
def send_booking_reminders(self):
    """
    Send reminders for bookings happening tomorrow.
    Runs daily at 8 AM.
    """
    from .models import Client, NotificationTemplate, Notification
    from .services import NotificationService
    from bookings.models import Booking

    try:
        template = NotificationTemplate.objects.get(
            template_type='booking_reminder',
            is_active=True
        )
    except NotificationTemplate.DoesNotExist:
        logger.warning("Booking reminder template not found or inactive")
        return "No active template"

    tomorrow = timezone.now().date() + timedelta(days=1)
    sent_count = 0

    # Get bookings for tomorrow
    tomorrows_bookings = Booking.objects.filter(
        scheduled_date=tomorrow,
        status='confirmed'
    ).select_related('client', 'coach', 'session_type', 'player')

    for booking in tomorrows_bookings:
        try:
            # Check if reminder already sent
            reminder_sent = Notification.objects.filter(
                client=booking.client,
                notification_type='booking_reminder',
                booking=booking
            ).exists()

            if reminder_sent:
                continue

            context = {
                'client_name': booking.client.user.first_name or booking.client.user.username,
                'player_name': booking.player.first_name if booking.player else 'Your player',
                'session_type': booking.session_type.name if booking.session_type else 'Training Session',
                'coach_name': str(booking.coach),
                'date': booking.scheduled_date.strftime('%B %d, %Y'),
                'time': booking.scheduled_time.strftime('%I:%M %p'),
                'booking_link': f"{getattr(settings, 'SITE_URL', '')}/portal/bookings/",
                'site_url': getattr(settings, 'SITE_URL', ''),
            }

            NotificationService.send_notification_from_template(booking.client, template, context)
            sent_count += 1

        except Exception as e:
            logger.error(f"Failed to send booking reminder for {booking}: {e}")

    logger.info(f"Sent booking reminders for {sent_count} bookings")
    return f"Sent booking reminders for {sent_count} bookings"


@shared_task(bind=True, max_retries=3)
def check_expiring_packages(self):
    """
    Send notifications for packages expiring in 7 days.
    Runs daily at 9 AM.
    """
    from .models import ClientPackage, NotificationTemplate, Notification
    from .services import NotificationService

    try:
        template = NotificationTemplate.objects.get(
            template_type='package_expiring',
            is_active=True
        )
    except NotificationTemplate.DoesNotExist:
        logger.warning("Package expiring template not found or inactive")
        return "No active template"

    # Check packages expiring in 7 days
    expiry_date = timezone.now().date() + timedelta(days=7)
    sent_count = 0

    expiring_packages = ClientPackage.objects.filter(
        status='active',
        expiry_date=expiry_date
    ).select_related('client', 'package')

    for client_package in expiring_packages:
        try:
            # Check if we've already sent expiry notification
            notification_sent = Notification.objects.filter(
                client=client_package.client,
                notification_type='package_expiring',
                package=client_package,
                created_at__gte=timezone.now() - timedelta(days=7)
            ).exists()

            if notification_sent:
                continue

            context = {
                'client_name': client_package.client.user.first_name or client_package.client.user.username,
                'package_name': client_package.package.name,
                'expiry_date': client_package.expiry_date.strftime('%B %d, %Y'),
                'days_remaining': 7,
                'sessions_remaining': client_package.sessions_remaining,
                'packages_link': f"{getattr(settings, 'SITE_URL', '')}/portal/packages/",
                'site_url': getattr(settings, 'SITE_URL', ''),
            }

            NotificationService.send_notification_from_template(
                client_package.client, template, context
            )
            sent_count += 1

        except Exception as e:
            logger.error(f"Failed to send package expiring notification for {client_package}: {e}")

    # Also check packages expiring in 3 days
    expiry_date_3days = timezone.now().date() + timedelta(days=3)
    expiring_soon = ClientPackage.objects.filter(
        status='active',
        expiry_date=expiry_date_3days
    ).select_related('client', 'package')

    for client_package in expiring_soon:
        try:
            context = {
                'client_name': client_package.client.user.first_name,
                'package_name': client_package.package.name,
                'expiry_date': client_package.expiry_date.strftime('%B %d, %Y'),
                'days_remaining': 3,
                'sessions_remaining': client_package.sessions_remaining,
                'packages_link': f"{getattr(settings, 'SITE_URL', '')}/portal/packages/",
                'site_url': getattr(settings, 'SITE_URL', ''),
            }

            NotificationService.send_notification_from_template(
                client_package.client, template, context
            )
            sent_count += 1

        except Exception as e:
            logger.error(f"Failed to send package expiring soon notification: {e}")

    logger.info(f"Sent package expiring notifications to {sent_count} clients")
    return f"Sent package expiring notifications to {sent_count} clients"


@shared_task(bind=True, max_retries=3)
def send_upcoming_event_reminders(self):
    """
    Send reminders about upcoming special events/clinics.
    Runs daily at 8 AM.
    """
    from .models import Package, Client, NotificationTemplate
    from .services import NotificationService

    try:
        template = NotificationTemplate.objects.get(
            template_type='upcoming_event',
            is_active=True
        )
    except NotificationTemplate.DoesNotExist:
        logger.info("Upcoming event template not found or inactive")
        return "No active template"

    tomorrow = timezone.now().date() + timedelta(days=1)
    sent_count = 0

    # Get special event packages starting tomorrow
    upcoming_events = Package.objects.filter(
        is_special=True,
        is_active=True,
        event_start_date=tomorrow
    )

    for event in upcoming_events:
        # Get clients who might be interested (have active packages)
        interested_clients = Client.objects.filter(
            packages__status='active',
            user__is_active=True
        ).distinct()

        for client in interested_clients:
            try:
                context = {
                    'client_name': client.user.first_name or client.user.username,
                    'event_name': event.name,
                    'event_date': event.event_start_date.strftime('%B %d, %Y'),
                    'event_location': event.event_location or 'TBD',
                    'event_link': f"{getattr(settings, 'SITE_URL', '')}/portal/packages/",
                    'site_url': getattr(settings, 'SITE_URL', ''),
                }

                NotificationService.send_notification_from_template(client, template, context)
                sent_count += 1

            except Exception as e:
                logger.error(f"Failed to send event reminder: {e}")

    logger.info(f"Sent event reminders to {sent_count} clients")
    return f"Sent event reminders to {sent_count} clients"


@shared_task(bind=True, max_retries=3)
def send_custom_campaign(self, template_id, target_filters=None):
    """
    Send custom marketing campaign to targeted clients.
    Triggered manually from admin.
    """
    from .models import Client, NotificationTemplate
    from .services import NotificationService

    try:
        template = NotificationTemplate.objects.get(id=template_id)
    except NotificationTemplate.DoesNotExist:
        logger.error(f"Template {template_id} not found")
        return "Template not found"

    target_filters = target_filters or template.target_filters or {}
    sent_count = 0

    # Start with all active clients
    clients = Client.objects.filter(user__is_active=True)

    # Apply filters
    if target_filters.get('has_active_package'):
        clients = clients.filter(
            packages__status='active',
            packages__expiry_date__gte=timezone.now().date()
        )

    if target_filters.get('inactive_weeks'):
        weeks = target_filters['inactive_weeks']
        cutoff = timezone.now() - timedelta(weeks=weeks)
        clients = clients.exclude(
            bookings__scheduled_date__gte=cutoff.date()
        )

    if target_filters.get('min_sessions'):
        clients = clients.filter(
            packages__sessions_used__gte=target_filters['min_sessions']
        )

    clients = clients.distinct()

    for client in clients:
        try:
            context = {
                'client_name': client.user.first_name or client.user.username,
                'site_url': getattr(settings, 'SITE_URL', ''),
                'booking_link': f"{getattr(settings, 'SITE_URL', '')}/portal/book/",
                'packages_link': f"{getattr(settings, 'SITE_URL', '')}/portal/packages/",
            }

            NotificationService.send_notification_from_template(client, template, context)
            sent_count += 1

        except Exception as e:
            logger.error(f"Failed to send campaign to {client}: {e}")

    logger.info(f"Custom campaign sent to {sent_count} clients")
    return f"Custom campaign sent to {sent_count} clients"


@shared_task
def cleanup_old_notifications():
    """
    Clean up notifications older than 90 days.
    Runs weekly on Sunday at 2 AM.
    """
    from .models import Notification

    cutoff = timezone.now() - timedelta(days=90)
    deleted_count, _ = Notification.objects.filter(
        created_at__lt=cutoff,
        status__in=['sent', 'read']
    ).delete()

    logger.info(f"Cleaned up {deleted_count} old notifications")
    return f"Cleaned up {deleted_count} old notifications"


@shared_task(bind=True, max_retries=3)
def send_assessment_notification_task(self, assessment_id):
    """
    Send assessment notification asynchronously.
    Called after coach submits an assessment.
    """
    from coaches.models import PlayerAssessment
    from .services import NotificationService

    try:
        assessment = PlayerAssessment.objects.get(id=assessment_id)
        NotificationService.send_assessment_notification(assessment)
        assessment.notification_sent = True
        assessment.save(update_fields=['notification_sent'])
        return f"Assessment notification sent for {assessment}"
    except PlayerAssessment.DoesNotExist:
        logger.error(f"Assessment {assessment_id} not found")
        return "Assessment not found"
    except Exception as e:
        logger.error(f"Failed to send assessment notification: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def send_booking_confirmation_task(self, booking_id):
    """
    Send booking confirmation asynchronously.
    Called after a booking is created.
    """
    from bookings.models import Booking
    from .services import NotificationService

    try:
        booking = Booking.objects.get(id=booking_id)
        NotificationService.send_booking_confirmation(booking)
        return f"Booking confirmation sent for {booking}"
    except Booking.DoesNotExist:
        logger.error(f"Booking {booking_id} not found")
        return "Booking not found"
    except Exception as e:
        logger.error(f"Failed to send booking confirmation: {e}")
        raise self.retry(exc=e, countdown=60)
