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

from clients.services import _booking_location, _location_map_url, _make_ics

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, name='clients.tasks.send_weekly_reminders')
def send_weekly_reminders(self):
    """
    Send weekly reminders to clients who haven't booked this week.
    Runs every Monday at 9 AM.
    """
    from clients.models import Client, NotificationTemplate
    from clients.services import NotificationService
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


@shared_task(bind=True, max_retries=3, name='clients.tasks.check_inactive_clients')
def check_inactive_clients(self):
    """
    Target clients who haven't booked in 3+ weeks with re-engagement campaign.
    Runs daily at 10 AM.
    """
    from clients.models import Client, NotificationTemplate, Notification
    from clients.services import NotificationService
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
                days_since = (timezone.localdate() - last_booking.scheduled_date).days
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


@shared_task(bind=True, max_retries=3, name='clients.tasks.send_booking_reminders')
def send_booking_reminders(self):
    """Send session reminders grouped by client — ONE email per client, even if they
    have multiple players with sessions coming up.

    Runs daily at 8 AM via Celery Beat.  Groups all qualifying bookings for a
    client into a single reminder email so a parent with two kids training tomorrow
    gets one email listing both sessions, not two separate emails.

    Uses the file-based emails/booking_reminder.html template directly — no DB
    NotificationTemplate record required.  Respects each client's
    reminder_hours_before preference and booking_reminders opt-out.
    Deduplicates per booking via Notification records.
    """
    from clients.models import Notification, NotificationPreference
    from clients.services import NotificationService
    from bookings.models import Booking
    from django.template.loader import render_to_string
    from datetime import datetime as _dt
    from collections import defaultdict

    site_url = getattr(settings, 'SITE_URL', 'https://atletasperformancecenter.com')
    today = timezone.localdate()
    now = timezone.now()
    sent_count = 0

    # Fetch confirmed bookings in the next 2 days (covers 24h and 48h prefs)
    upcoming = Booking.objects.filter(
        scheduled_date__in=[today + timedelta(days=1), today + timedelta(days=2)],
        status='confirmed',
    ).select_related('client__user', 'coach__user', 'session_type', 'player').order_by(
        'scheduled_date', 'scheduled_time'
    )

    # Group bookings by client
    by_client = defaultdict(list)
    for booking in upcoming:
        by_client[booking.client_id].append(booking)

    for client_id, bookings in by_client.items():
        try:
            client = bookings[0].client

            # Load preferences once per client
            try:
                prefs = client.notification_preferences
                hours_before = prefs.reminder_hours_before or 24
                method = prefs.booking_reminders
                opted_out = prefs.email_opt_out
            except NotificationPreference.DoesNotExist:
                hours_before = 24
                method = 'email'
                opted_out = False

            # Master opt-out / suppression list — no email of any kind.
            from clients.models import EmailSuppression
            if opted_out or method == 'none' or EmailSuppression.is_suppressed(client.user.email):
                continue

            # Filter to bookings that are in the reminder window and not yet reminded
            qualifying = []
            for b in bookings:
                session_dt = _dt.combine(b.scheduled_date, b.scheduled_time)
                aware_session = timezone.make_aware(session_dt)
                hours_until = (aware_session - now).total_seconds() / 3600

                # Within window (with 4h buffer for daily task timing) and not passed
                if not (0 < hours_until <= hours_before + 4):
                    continue

                # Skip if already reminded for this specific booking
                if Notification.objects.filter(
                    client=client,
                    notification_type='booking_reminder',
                    booking=b,
                ).exists():
                    continue

                qualifying.append(b)

            if not qualifying:
                continue

            # Build sessions list for the template
            sessions = []
            for b in qualifying:
                loc = _booking_location(b)
                sessions.append({
                    'player_name':      b.player.first_name if b.player else '',
                    'session_type':     b.session_type.name if b.session_type else 'Training Session',
                    'session_duration': f"{b.session_type.duration_minutes} min" if b.session_type else '',
                    'location':         loc,
                    'location_map_url': _location_map_url(loc),
                    'coach_name':       b.coach.user.get_full_name() or str(b.coach),
                    'date':             b.scheduled_date.strftime('%A, %B %-d, %Y'),
                    'time':             b.scheduled_time.strftime('%-I:%M %p'),
                    'is_tomorrow':      b.scheduled_date == today + timedelta(days=1),
                })

            client_name = client.user.first_name or client.user.username
            multiple = len(sessions) > 1
            tomorrow_only = all(s['is_tomorrow'] for s in sessions)

            if multiple:
                subject = f"⏰ Reminder: {len(sessions)} Sessions Coming Up!"
            elif tomorrow_only:
                subject = "⏰ Reminder: Training Tomorrow!"
            else:
                subject = "⏰ Reminder: Upcoming Training Session"

            from clients.models import make_unsubscribe_url
            ctx = {
                'client_name':  client_name,
                'sessions':     sessions,
                'multiple':     multiple,
                'booking_link': f"{site_url}/portal/bookings/",
                'site_url':     site_url,
                'current_year': timezone.now().year,
                'unsubscribe_url': make_unsubscribe_url(client.user.email, site_url),
            }

            html_body = render_to_string('emails/booking_reminder.html', ctx)
            text_lines = [f"Reminder: {len(sessions)} upcoming session(s):\n"]
            for s in sessions:
                text_lines.append(f"  • {s['session_type']} — {s['date']} at {s['time']} with {s['coach_name']}")
            text_lines.append(f"\nView all: {site_url}/portal/bookings/")

            # Build ICS: one file per booking; for a single session use session.ics,
            # for multiple use session-1.ics, session-2.ics, etc.
            from django.core.mail import EmailMultiAlternatives
            from django.template.loader import render_to_string as _rts
            base_ctx = {'content': html_body, 'subject': subject, **ctx}
            full_html = _rts('emails/base_email.html', base_ctx)

            msg_obj = EmailMultiAlternatives(
                subject=subject,
                body='\n'.join(text_lines),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[client.user.email],
            )
            msg_obj.attach_alternative(full_html, 'text/html')
            for i, b in enumerate(qualifying):
                try:
                    ics_data = _make_ics(b, location=_booking_location(b))
                    fname = 'session.ics' if len(qualifying) == 1 else f'session-{i+1}.ics'
                    msg_obj.attach(fname, ics_data, 'text/calendar')
                except Exception:
                    pass
            try:
                msg_obj.send()
                success, msg = True, 'Sent'
            except Exception as exc:
                success, msg = False, str(exc)

            # Create one Notification record per booking for deduplication on next run
            sent_now = timezone.now() if success else None
            for b in qualifying:
                Notification.objects.create(
                    client=client,
                    notification_type='booking_reminder',
                    title=subject,
                    message=f"Reminder for {b.session_type.name if b.session_type else 'session'} on {b.scheduled_date}",
                    method='email',
                    booking=b,
                    status='sent' if success else 'failed',
                    sent_at=sent_now,
                )

            if success:
                sent_count += 1
                logger.info('Reminder sent to %s (%d session(s))', client, len(qualifying))
            else:
                logger.error('Reminder failed for client %s: %s', client, msg)

        except Exception as e:
            logger.error('send_booking_reminders: failed for client %s — %s', client_id, e)

    logger.info('Sent booking reminders to %d client(s)', sent_count)
    return f"Sent booking reminders to {sent_count} client(s)"


@shared_task(bind=True, max_retries=3, name='clients.tasks.check_expiring_packages')
def check_expiring_packages(self):
    """
    Send notifications for packages expiring in 7 days.
    Runs daily at 9 AM.
    """
    from clients.models import ClientPackage, NotificationTemplate, Notification
    from clients.services import NotificationService

    try:
        template = NotificationTemplate.objects.get(
            template_type='package_expiring',
            is_active=True
        )
    except NotificationTemplate.DoesNotExist:
        logger.warning("Package expiring template not found or inactive")
        return "No active template"

    # Check packages expiring in 7 days
    expiry_date = timezone.localdate() + timedelta(days=7)
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
    expiry_date_3days = timezone.localdate() + timedelta(days=3)
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

    # APC Select — manual-renewal reminders (30-day and 7-day)
    # Only fires for Select packages WITHOUT a Stripe subscription (manual-pay members)
    for days_ahead in (30, 7):
        select_expiry = timezone.localdate() + timedelta(days=days_ahead)
        manual_select = ClientPackage.objects.filter(
            package__package_type='select',
            status='active',
            expiry_date=select_expiry,
            stripe_subscription_id='',   # auto-renew subs handled by Stripe webhooks
        ).select_related('client__user', 'package')
        for cp in manual_select:
            try:
                already = Notification.objects.filter(
                    client=cp.client,
                    notification_type='promotional',
                    title__contains='APC Select Renewal',
                    created_at__gte=timezone.now() - timedelta(days=days_ahead - 1),
                ).exists()
                if already:
                    continue
                site_url = getattr(settings, 'SITE_URL', 'https://atletasperformancecenter.com')
                Notification.objects.create(
                    client=cp.client,
                    notification_type='promotional',
                    title=f'APC Select Renewal Reminder — {days_ahead} Days',
                    message=(
                        f'Your APC Select membership expires on {cp.expiry_date.strftime("%B %-d, %Y")} '
                        f'({days_ahead} days from now). Renew at {site_url}/portal/packages/ '
                        f'to keep your membership and team access.'
                    ),
                    method='in_app',
                )
                sent_count += 1
            except Exception as e:
                logger.error('Failed to send Select renewal reminder for %s: %s', cp, e)

    logger.info(f"Sent package expiring notifications to {sent_count} clients")
    return f"Sent package expiring notifications to {sent_count} clients"


@shared_task(bind=True, max_retries=3, name='clients.tasks.send_upcoming_event_reminders')
def send_upcoming_event_reminders(self):
    """
    Send reminders about upcoming special events/clinics.
    Runs daily at 8 AM.
    """
    from clients.models import Package, Client, NotificationTemplate
    from clients.services import NotificationService

    try:
        template = NotificationTemplate.objects.get(
            template_type='upcoming_event',
            is_active=True
        )
    except NotificationTemplate.DoesNotExist:
        logger.info("Upcoming event template not found or inactive")
        return "No active template"

    tomorrow = timezone.localdate() + timedelta(days=1)
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


@shared_task(bind=True, max_retries=3, name='clients.tasks.send_custom_campaign')
def send_custom_campaign(self, template_id, target_filters=None):
    """
    Send custom marketing campaign to targeted clients.
    Triggered manually from admin.
    """
    from clients.models import Client, NotificationTemplate
    from clients.services import NotificationService

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
            packages__expiry_date__gte=timezone.localdate()
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


@shared_task(name='clients.tasks.cleanup_old_notifications')
def cleanup_old_notifications():
    """
    Clean up notifications older than 90 days.
    Runs weekly on Sunday at 2 AM.
    """
    from clients.models import Notification

    cutoff = timezone.now() - timedelta(days=90)
    deleted_count, _ = Notification.objects.filter(
        created_at__lt=cutoff,
        status__in=['sent', 'read']
    ).delete()

    logger.info(f"Cleaned up {deleted_count} old notifications")
    return f"Cleaned up {deleted_count} old notifications"


@shared_task(bind=True, max_retries=3, name='clients.tasks.send_assessment_notification_task')
def send_assessment_notification_task(self, assessment_id):
    """
    Send assessment notification asynchronously.
    Called after coach submits an assessment.
    """
    from coaches.models import PlayerAssessment
    from clients.services import NotificationService

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


@shared_task(bind=True, max_retries=2, name='clients.tasks.flush_notification_group')
def flush_notification_group(self, group_key):
    """Flush a NotificationOutbox group and send ONE combined email.

    Runs after the coalescing window expires.  Reads all accumulated events,
    delegates rendering + sending to NotificationService.send_grouped(), then
    deletes the transient outbox record.

    Retries up to 2 times (60 s apart) on transient failures so a brief SMTP
    hiccup doesn't permanently lose the notification.
    """
    from clients.models import NotificationOutbox
    from clients.services import NotificationService

    try:
        outbox = NotificationOutbox.objects.get(group_key=group_key)
    except NotificationOutbox.DoesNotExist:
        return  # Already processed or cleaned up — nothing to do

    try:
        NotificationService.send_grouped(outbox.client, outbox.events)
        outbox.delete()
        logger.info('Flushed notification group %s (%d events)', group_key, len(outbox.events))
    except Exception as exc:
        logger.exception('flush_notification_group failed for %s', group_key)
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3, name='clients.tasks.send_booking_confirmation_task')
def send_booking_confirmation_task(self, booking_id):
    """
    Send booking confirmation asynchronously.
    Called after a booking is created.
    """
    from bookings.models import Booking
    from clients.services import NotificationService

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
