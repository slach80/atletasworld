"""
Notification Service for sending emails and SMS.
"""
import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class NotificationService:
    """Centralized service for sending notifications."""

    @staticmethod
    def send_email(to_email, subject, html_content, text_content, context=None):
        """Send email with HTML and plain text versions."""
        try:
            # Wrap in base email template if context provided
            if context:
                full_html = render_to_string('emails/base_email.html', {
                    'content': html_content,
                    'subject': subject,
                    **context
                })
            else:
                full_html = html_content

            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to_email] if isinstance(to_email, str) else to_email
            )
            msg.attach_alternative(full_html, "text/html")
            msg.send()

            logger.info(f"Email sent to {to_email}: {subject}")
            return True, "Sent"

        except Exception as e:
            logger.error(f"Email failed to {to_email}: {str(e)}")
            return False, str(e)

    @staticmethod
    def send_sms(to_phone, message):
        """Send SMS using Twilio (if enabled and configured)."""
        try:
            # Check if SMS is enabled (PAID service - disabled by default)
            if not getattr(settings, 'SMS_ENABLED', False):
                logger.info("SMS disabled (paid service). Enable with SMS_ENABLED=True in .env")
                return False, "SMS disabled (enable in settings)"

            # Check if Twilio is configured
            if not getattr(settings, 'TWILIO_ACCOUNT_SID', '') or not getattr(settings, 'TWILIO_AUTH_TOKEN', ''):
                logger.warning("Twilio not configured, SMS not sent")
                return False, "Twilio not configured"

            from twilio.rest import Client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

            message = client.messages.create(
                body=message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=to_phone
            )

            logger.info(f"SMS sent to {to_phone}")
            return True, "Sent"

        except ImportError:
            logger.warning("Twilio package not installed")
            return False, "Twilio not installed"
        except Exception as e:
            logger.error(f"SMS failed to {to_phone}: {str(e)}")
            return False, str(e)

    @classmethod
    def send_notification_from_template(cls, client, template, context=None):
        """Send notification using a template based on client preferences."""
        from .models import Notification, NotificationPreference

        context = context or {}
        context['client_name'] = client.user.first_name or client.user.username
        context['site_url'] = getattr(settings, 'SITE_URL', 'http://localhost:8000')

        results = []

        # Get client preferences
        try:
            prefs = client.notification_preferences
        except NotificationPreference.DoesNotExist:
            prefs = None

        # Determine notification method based on template type
        method = 'email'  # Default
        if prefs:
            pref_map = {
                'booking_confirmed': prefs.booking_confirmations,
                'booking_reminder': prefs.booking_reminders,
                'booking_cancelled': prefs.booking_cancellations,
                'assessment_ready': prefs.assessment_notifications,
                'promotional': prefs.promotional_updates,
            }
            method = pref_map.get(template.template_type, 'email')

        if method == 'none':
            return results

        # Send email
        if method in ['email', 'both'] and template.email_subject:
            success, message = cls.send_email(
                to_email=client.user.email,
                subject=template.render_email_subject(context),
                html_content=template.render_email_body_html(context),
                text_content=template.render_email_body_text(context),
                context=context
            )
            results.append(('email', success, message))

            # Log notification
            Notification.objects.create(
                client=client,
                notification_type=template.template_type,
                title=template.render_email_subject(context),
                message=template.render_email_body_text(context),
                method='email',
                status='sent' if success else 'failed',
                sent_at=timezone.now() if success else None
            )

        # Send SMS
        if method in ['sms', 'both'] and template.sms_body:
            phone = getattr(client, 'phone', None)
            if phone:
                success, message = cls.send_sms(
                    to_phone=phone,
                    message=template.render_sms_body(context)
                )
                results.append(('sms', success, message))

                Notification.objects.create(
                    client=client,
                    notification_type=template.template_type,
                    title=f"SMS: {template.name}",
                    message=template.render_sms_body(context),
                    method='sms',
                    status='sent' if success else 'failed',
                    sent_at=timezone.now() if success else None
                )

        return results

    @classmethod
    def send_booking_confirmation(cls, booking):
        """Send booking confirmation notification."""
        from .models import NotificationTemplate

        try:
            template = NotificationTemplate.objects.get(
                template_type='booking_confirmed',
                is_active=True
            )
        except NotificationTemplate.DoesNotExist:
            # Use default inline notification
            from .models import Notification
            Notification.objects.create(
                client=booking.client,
                notification_type='booking_confirmed',
                title='Booking Confirmed',
                message=f'Your {booking.session_type.name if booking.session_type else "session"} on {booking.scheduled_date} at {booking.scheduled_time} has been confirmed.',
                method='email',
                booking=booking
            )
            return

        context = {
            'session_type': booking.session_type.name if booking.session_type else 'Training Session',
            'coach_name': str(booking.coach),
            'date': booking.scheduled_date.strftime('%B %d, %Y'),
            'time': booking.scheduled_time.strftime('%I:%M %p'),
            'booking_link': f"{getattr(settings, 'SITE_URL', '')}/portal/bookings/",
        }

        cls.send_notification_from_template(booking.client, template, context)

    @classmethod
    def send_booking_reminder(cls, booking):
        """Send booking reminder notification."""
        from .models import NotificationTemplate

        try:
            template = NotificationTemplate.objects.get(
                template_type='booking_reminder',
                is_active=True
            )
        except NotificationTemplate.DoesNotExist:
            return

        context = {
            'session_type': booking.session_type.name if booking.session_type else 'Training Session',
            'coach_name': str(booking.coach),
            'date': booking.scheduled_date.strftime('%B %d, %Y'),
            'time': booking.scheduled_time.strftime('%I:%M %p'),
            'hours_until': 24,  # Configurable
        }

        cls.send_notification_from_template(booking.client, template, context)

    @classmethod
    def send_assessment_notification(cls, assessment):
        """Send assessment ready notification to parent."""
        from .models import NotificationTemplate

        try:
            template = NotificationTemplate.objects.get(
                template_type='assessment_ready',
                is_active=True
            )
        except NotificationTemplate.DoesNotExist:
            from .models import Notification
            Notification.objects.create(
                client=assessment.player.client,
                notification_type='assessment_ready',
                title='New Assessment Available',
                message=f'Coach {assessment.coach.user.first_name} has submitted an assessment for {assessment.player.first_name}.',
                method='email'
            )
            return

        context = {
            'player_name': assessment.player.first_name,
            'coach_name': assessment.coach.user.first_name,
            'training_type': assessment.get_training_type_display(),
            'date': assessment.assessment_date.strftime('%B %d, %Y'),
            'assessment_link': f"{getattr(settings, 'SITE_URL', '')}/portal/assessments/",
        }

        cls.send_notification_from_template(assessment.player.client, template, context)

    @classmethod
    def send_package_expiring_notice(cls, client_package, days_until_expiry):
        """Send package expiring soon notification."""
        from .models import NotificationTemplate

        try:
            template = NotificationTemplate.objects.get(
                template_type='package_expiring',
                is_active=True
            )
        except NotificationTemplate.DoesNotExist:
            return

        context = {
            'package_name': client_package.package.name,
            'expiry_date': client_package.expiry_date.strftime('%B %d, %Y'),
            'days_remaining': days_until_expiry,
            'sessions_remaining': client_package.sessions_remaining,
            'packages_link': f"{getattr(settings, 'SITE_URL', '')}/portal/packages/",
        }

        cls.send_notification_from_template(client_package.client, template, context)

    @staticmethod
    def send_push_notification(client, title, body, url=None, icon=None):
        """Send web push notification to all client's subscribed devices."""
        try:
            # Check if push notifications are enabled
            if not getattr(settings, 'PUSH_NOTIFICATIONS_ENABLED', False):
                logger.info("Push notifications disabled. Enable with PUSH_NOTIFICATIONS_ENABLED=True in .env")
                return False, "Push notifications disabled (enable in settings)"

            from pywebpush import webpush, WebPushException
            from .models import PushSubscription
            import json

            vapid_private_key = getattr(settings, 'VAPID_PRIVATE_KEY', None)
            vapid_claims = {
                'sub': f"mailto:{getattr(settings, 'DEFAULT_FROM_EMAIL', 'admin@example.com')}"
            }

            if not vapid_private_key:
                logger.warning("VAPID_PRIVATE_KEY not configured, push notifications disabled")
                return False, "VAPID not configured"

            subscriptions = PushSubscription.objects.filter(
                client=client,
                is_active=True
            )

            if not subscriptions.exists():
                return False, "No active push subscriptions"

            payload = json.dumps({
                'title': title,
                'body': body,
                'icon': icon or '/static/img/icon-192.png',
                'url': url or getattr(settings, 'SITE_URL', ''),
                'timestamp': timezone.now().isoformat(),
            })

            sent_count = 0
            for subscription in subscriptions:
                try:
                    webpush(
                        subscription_info={
                            'endpoint': subscription.endpoint,
                            'keys': {
                                'p256dh': subscription.p256dh_key,
                                'auth': subscription.auth_key,
                            }
                        },
                        data=payload,
                        vapid_private_key=vapid_private_key,
                        vapid_claims=vapid_claims
                    )
                    subscription.last_used_at = timezone.now()
                    subscription.save(update_fields=['last_used_at'])
                    sent_count += 1
                except WebPushException as e:
                    if e.response and e.response.status_code in [404, 410]:
                        # Subscription expired or invalid
                        subscription.is_active = False
                        subscription.save(update_fields=['is_active'])
                    logger.error(f"Push notification failed: {e}")

            return sent_count > 0, f"Sent to {sent_count} device(s)"

        except ImportError:
            logger.warning("pywebpush not installed")
            return False, "pywebpush not installed"
        except Exception as e:
            logger.error(f"Push notification error: {e}")
            return False, str(e)

    @classmethod
    def send_all_channels(cls, client, title, message, notification_type='promotional', context=None):
        """Send notification via all available channels (email, SMS, push)."""
        results = []

        # Get preferences
        from .models import NotificationPreference
        try:
            prefs = client.notification_preferences
        except NotificationPreference.DoesNotExist:
            prefs = None

        method = 'email'
        if prefs:
            pref_map = {
                'booking_confirmed': prefs.booking_confirmations,
                'booking_reminder': prefs.booking_reminders,
                'promotional': prefs.promotional_updates,
            }
            method = pref_map.get(notification_type, 'email')

        if method == 'none':
            return results

        context = context or {}
        context['client_name'] = client.user.first_name or client.user.username
        context['site_url'] = getattr(settings, 'SITE_URL', '')

        # Email
        if method in ['email', 'both']:
            success, msg = cls.send_email(
                to_email=client.user.email,
                subject=title,
                html_content=message,
                text_content=message,
                context=context
            )
            results.append(('email', success, msg))

        # SMS
        if method in ['sms', 'both'] and client.phone:
            success, msg = cls.send_sms(client.phone, message[:160])
            results.append(('sms', success, msg))

        # Push (always attempt if subscribed)
        success, msg = cls.send_push_notification(client, title, message[:200])
        if success:
            results.append(('push', success, msg))

        return results
