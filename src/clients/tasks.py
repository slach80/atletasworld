"""
Celery tasks for automated notifications.

Note: All tasks can run synchronously when CELERY_ENABLED=False.
Use run_task() helper to automatically choose sync/async execution.
"""
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from email.mime.image import MIMEImage
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


@shared_task(bind=True, max_retries=0, ignore_result=True)
def send_bulk_email_task(self, recipients=None, subject='', message='', from_email='',
                         send_as_html=False, broadcast_id=None,
                         recipient_group='', extra_params=None):
    """
    Send bulk email. Two calling modes:
      1. recipients=[...] — explicit list (used by attachment/sync path)
      2. recipient_group='contacts_all' + extra_params={...} — task resolves the list
         (used by the async no-attachment path; keeps the view instant)
    Updates EmailBroadcast log when done.
    Uses a single persistent SMTP connection to avoid Gmail rate-limiting.
    """
    import re
    from django.core.mail import EmailMessage, get_connection
    from .models import EmailBroadcast

    # Resolve recipient list from group if not provided directly
    if recipients is None:
        from atletasworld.admin_views import _resolve_recipient_emails
        extra = extra_params or {}
        resolved = _resolve_recipient_emails(
            recipient_group,
            package_id=extra.get('package_id', ''),
            contact_source=extra.get('contact_source', ''),
            individual_emails=extra.get('individual_emails') or [],
        )
        recipients = list(resolved)
        if broadcast_id:
            try:
                EmailBroadcast.objects.filter(id=broadcast_id).update(
                    recipient_emails=','.join(recipients)
                )
            except Exception as e:
                logger.warning(f"send_bulk_email_task: could not update recipient_emails: {e}")

    if not recipients:
        logger.warning(f"send_bulk_email_task: no recipients for group '{recipient_group}'")
        if broadcast_id:
            EmailBroadcast.objects.filter(id=broadcast_id).update(sent_count=0, failed_count=0)
        return "No recipients"

    sent_count = 0
    failed_count = 0

    site_url = settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'https://atletasperformancecenter.com'

    # Build body once — it's identical for every recipient
    if send_as_html:
        html_message = message.replace('\n', '<br>')
        body = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif; line-height: 1.6; color: #333333; background-color: #f5f5f5; margin: 0; padding: 0; }}
    .email-wrapper {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
    .email-header {{ background: linear-gradient(135deg, #1a1a1a 0%, #2c3e50 100%); padding: 30px; text-align: center; }}
    .email-header img {{ max-height: 60px; width: auto; }}
    .email-header h1 {{ color: #ffffff; margin: 12px 0 0 0; font-size: 22px; font-weight: 600; letter-spacing: 0.5px; }}
    .email-body {{ padding: 40px 30px; }}
    .email-body p {{ margin: 0 0 15px 0; color: #555555; }}
    .divider {{ border: none; border-top: 1px solid #eeeeee; margin: 30px 0; }}
    .signature {{ font-size: 14px; color: #444444; }}
    .signature strong {{ color: #1a1a1a; font-size: 15px; }}
    .signature .title {{ color: #888888; font-size: 13px; margin: 2px 0; }}
    .signature .contact {{ color: #888888; font-size: 13px; margin: 2px 0; }}
    .signature .contact a {{ color: #1a1a1a; text-decoration: none; }}
    .signature-bar {{ width: 40px; height: 3px; background-color: #D7FF00; margin: 10px 0; }}
    .email-footer {{ background-color: #1a1a1a; padding: 25px 30px; text-align: center; }}
    .email-footer p {{ color: #888888; font-size: 12px; margin: 4px 0; }}
    .email-footer a {{ color: #D7FF00; text-decoration: none; }}
    .footer-logo {{ color: #ffffff; font-size: 15px; font-weight: 700; letter-spacing: 1px; margin-bottom: 8px; }}
</style>
</head>
<body>
<div class="email-wrapper">
    <div class="email-header">
        <img src="{site_url}/static/img/apc-logo-yellow.png" alt="Atletas Performance Center" onerror="this.style.display=\'none\'">
        <h1>Atletas Performance Center</h1>
    </div>
    <div class="email-body">
        {html_message}
        <hr class="divider">
        <div class="signature">
            <div class="signature-bar"></div>
            <strong>Atletas Performance Center</strong><br>
            <div class="title">Professional Soccer Training</div>
            <div class="contact">📧 <a href="mailto:info@atletasperformancecenter.com">info@atletasperformancecenter.com</a></div>
            <div class="contact">🌐 <a href="{site_url}">{site_url.replace("https://", "")}</a></div>
        </div>
    </div>
    <div class="email-footer">
        <div class="footer-logo">APC</div>
        <p>
            <a href="https://www.instagram.com/atletasworld/" target="_blank">Instagram</a> &nbsp;|&nbsp;
            <a href="https://www.facebook.com/atletasworld/" target="_blank">Facebook</a>
        </p>
        <p style="margin-top: 12px; font-size: 11px; color: #555555;">
            &copy; 2026 Atletas Performance Center. All rights reserved.
        </p>
    </div>
</div>
</body>
</html>'''
    else:
        body = message + (
            f"\n\n--\nAtletas Performance Center\nProfessional Soccer Training\n"
            f"info@atletasperformancecenter.com\n{site_url}"
        )

    # Load attachment file data from disk (saved by the view before dispatching to Celery)
    extra = extra_params or {}
    attachment_files = []   # list of (name, data, content_type)
    inline_image_file = None  # (name, data, content_type)

    for att_info in extra.get('attachments') or []:
        try:
            with open(att_info['path'], 'rb') as fh:
                attachment_files.append((att_info['name'], fh.read(), att_info['content_type']))
        except Exception as e:
            logger.warning(f"send_bulk_email_task: could not read attachment {att_info.get('path')}: {e}")

    img_info = extra.get('inline_image')
    if img_info:
        try:
            with open(img_info['path'], 'rb') as fh:
                inline_image_file = (img_info['name'], fh.read(), img_info['content_type'])
        except Exception as e:
            logger.warning(f"send_bulk_email_task: could not read inline_image {img_info.get('path')}: {e}")

    # Reuse one SMTP connection for all recipients to avoid Gmail rate-limiting
    connection = get_connection()
    try:
        connection.open()
    except Exception as e:
        logger.error(f"send_bulk_email_task: failed to open SMTP connection: {e}")
        if broadcast_id:
            EmailBroadcast.objects.filter(id=broadcast_id).update(
                sent_count=0, failed_count=len(recipients))
        return f"Sent 0, failed {len(recipients)} (SMTP connection failed)"

    try:
        for email_addr in recipients:
            # Skip malformed addresses (commas, spaces, missing domain dot)
            if not re.match(r'^[^@\s,]+@[^@\s,]+\.[^@\s,]+$', email_addr):
                failed_count += 1
                logger.warning(f"send_bulk_email_task: skipping malformed address: {email_addr!r}")
                continue

            try:
                if inline_image_file or (send_as_html and attachment_files):
                    # HTML email with inline image or HTML + attachments
                    this_body = body
                    if inline_image_file:
                        img_name, img_data, img_ctype = inline_image_file
                        img_tag = '<img src="cid:inline_image" style="max-width:100%;height:auto;margin:20px 0"><br><br>'
                        # Inject image tag before body content
                        this_body = this_body.replace('<div class="email-body">', f'<div class="email-body">{img_tag}', 1)
                    email_msg = EmailMessage(subject=subject, body=this_body,
                                             from_email=from_email, to=[email_addr],
                                             connection=connection)
                    email_msg.content_subtype = 'html'
                    if inline_image_file:
                        img_name, img_data, img_ctype = inline_image_file
                        mime_image = MIMEImage(img_data)
                        mime_image.add_header('Content-ID', '<inline_image>')
                        mime_image.add_header('Content-Disposition', 'inline', filename=img_name)
                        email_msg.attach(mime_image)
                    for att_name, att_data, att_ctype in attachment_files:
                        email_msg.attach(att_name, att_data, att_ctype)
                else:
                    email_msg = EmailMessage(subject=subject, body=body,
                                             from_email=from_email, to=[email_addr],
                                             connection=connection)
                    if send_as_html:
                        email_msg.content_subtype = 'html'
                    for att_name, att_data, att_ctype in attachment_files:
                        email_msg.attach(att_name, att_data, att_ctype)
                email_msg.send(fail_silently=False)
                sent_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"send_bulk_email_task: failed to send to {email_addr}: {e}")
                # Reopen connection in case it was dropped
                try:
                    connection.close()
                    connection.open()
                except Exception:
                    pass
    finally:
        try:
            connection.close()
        except Exception:
            pass

    # Clean up temp files saved by the view
    import os
    for att_info in extra.get('attachments') or []:
        try:
            os.unlink(att_info['path'])
        except Exception:
            pass
    if img_info:
        try:
            os.unlink(img_info['path'])
        except Exception:
            pass

    if broadcast_id:
        try:
            EmailBroadcast.objects.filter(id=broadcast_id).update(
                sent_count=sent_count,
                failed_count=failed_count,
            )
        except Exception as e:
            logger.error(f"send_bulk_email_task: failed to update broadcast log {broadcast_id}: {e}")

    logger.info(f"send_bulk_email_task: sent={sent_count} failed={failed_count} broadcast_id={broadcast_id}")
    return f"Sent {sent_count}, failed {failed_count}"


# ── Stripe Health Check ────────────────────────────────────────────────────────

STRIPE_ALERT_RECIPIENT = 'info@atletasperformancecenter.com'


@shared_task(name='clients.tasks.check_stripe_health')
def check_stripe_health():
    """
    Daily health check for Stripe connectivity.
    Sends an alert email to info@ if:
      - STRIPE_SECRET_KEY is missing or empty
      - The key is in test mode (sk_test_) instead of live (sk_live_)
      - The Stripe API call fails (network error, invalid key, etc.)
    """
    from django.core.mail import send_mail

    key = getattr(settings, 'STRIPE_SECRET_KEY', '') or ''

    issues = []

    if not key:
        issues.append('STRIPE_SECRET_KEY is not set.')
    elif not key.startswith(('sk_live', 'rk_live')):
        issues.append(f'Stripe key is in TEST mode (starts with "{key[:10]}…"). Switch to a live key for real payments.')

    if key:
        try:
            import stripe
            stripe.api_key = key
            stripe.Balance.retrieve()
        except Exception as e:
            issues.append(f'Stripe API connection failed: {e}')

    if issues:
        body = (
            "⚠️ Stripe Health Alert — Atletas Performance Center\n\n"
            + "\n".join(f"• {issue}" for issue in issues)
            + "\n\nPlease review your Stripe configuration at "
            "https://atletasperformancecenter.com/owner-portal/payments/\n"
        )
        try:
            send_mail(
                subject='⚠️ Stripe Connection Issue — APC',
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[STRIPE_ALERT_RECIPIENT],
                fail_silently=False,
            )
            logger.warning(f"check_stripe_health: alert sent — {issues}")
        except Exception as e:
            logger.error(f"check_stripe_health: failed to send alert email: {e}")
        return f"Alert sent: {issues}"

    logger.info("check_stripe_health: Stripe OK")
    return "OK"
