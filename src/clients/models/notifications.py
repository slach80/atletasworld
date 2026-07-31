from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
from django_prometheus.models import ExportModelOperationsMixin

from .core import Client


# Salt for signed one-click unsubscribe links. The signed value is just the
# recipient's email address, so any recipient (client, coach, or bare contact)
# gets a working unsubscribe link with no DB token to pre-provision.
UNSUBSCRIBE_SALT = 'atletas.email.unsubscribe'


def make_unsubscribe_url(email, site_url=None):
    """Return an absolute, signed one-click unsubscribe URL for any email address."""
    from django.core import signing
    from django.urls import reverse
    if site_url is None:
        site_url = getattr(settings, 'SITE_URL', 'https://atletasperformancecenter.com')
    token = signing.dumps(email, salt=UNSUBSCRIBE_SALT)
    return f"{site_url.rstrip('/')}{reverse('email_unsubscribe_oneclick', args=[token])}"


class EmailSuppression(models.Model):
    """Universal email opt-out list keyed by address.

    Covers everyone we email — clients, coaches, and un-registered contacts —
    so suppression works even for recipients with no Client/NotificationPreference
    row. The presence of a row (active=True) means: send no further emails.
    """
    email = models.EmailField(unique=True, db_index=True)
    active = models.BooleanField(default=True)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.email} ({'suppressed' if self.active else 'resubscribed'})"

    @classmethod
    def is_suppressed(cls, email):
        if not email:
            return False
        return cls.objects.filter(email__iexact=email.strip(), active=True).exists()

    @classmethod
    def suppress(cls, email, reason=''):
        email = (email or '').strip()
        if not email:
            return None
        obj, _ = cls.objects.update_or_create(
            email=email,
            defaults={'active': True, 'reason': reason},
        )
        return obj

    @classmethod
    def resubscribe(cls, email):
        email = (email or '').strip()
        if not email:
            return
        cls.objects.filter(email__iexact=email).update(active=False)


class UnsubscribeToken(models.Model):
    """One-time-use token for password-less email unsubscribe flow."""
    client = models.OneToOneField('Client', on_delete=models.CASCADE, related_name='unsubscribe_token')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"UnsubscribeToken for {self.client}"

    @classmethod
    def get_or_create_for_client(cls, client):
        import secrets
        obj, created = cls.objects.get_or_create(client=client)
        now = timezone.now()
        if created or obj.expires_at <= now:
            obj.token = secrets.token_urlsafe(48)
            obj.expires_at = now + timezone.timedelta(days=30)
            obj.save()
        return obj

    def is_valid(self):
        return timezone.now() < self.expires_at


class NotificationPreference(models.Model):
    """Client notification preferences."""
    NOTIFICATION_METHOD_CHOICES = [
        ('email', 'Email'),
        ('sms', 'SMS Text Message'),
        ('both', 'Email and SMS'),
        ('none', 'No Notifications'),
    ]

    client = models.OneToOneField(Client, on_delete=models.CASCADE, related_name='notification_preferences')

    # Master kill-switch — when True, NO emails of any kind are sent to this client.
    # Set by the one-click "Unsubscribe" link in every email footer.
    email_opt_out = models.BooleanField(
        default=False,
        help_text="When checked, the client receives no emails at all (one-click unsubscribe).",
    )
    email_opt_out_at = models.DateTimeField(null=True, blank=True)

    # Notification types
    booking_confirmations = models.CharField(max_length=10, choices=NOTIFICATION_METHOD_CHOICES, default='email')
    booking_reminders = models.CharField(max_length=10, choices=NOTIFICATION_METHOD_CHOICES, default='email')
    booking_cancellations = models.CharField(max_length=10, choices=NOTIFICATION_METHOD_CHOICES, default='email')
    purchase_confirmations = models.CharField(max_length=10, choices=NOTIFICATION_METHOD_CHOICES, default='email')
    assessment_notifications = models.CharField(max_length=10, choices=NOTIFICATION_METHOD_CHOICES, default='email')
    promotional_updates = models.CharField(max_length=10, choices=NOTIFICATION_METHOD_CHOICES, default='none')

    # Reminder timing
    reminder_hours_before = models.IntegerField(default=24, help_text="Hours before session to send reminder")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Notification preferences for {self.client}"


class Notification(models.Model):
    """Track sent notifications."""
    NOTIFICATION_TYPE_CHOICES = [
        ('booking_confirmed', 'Booking Confirmed'),
        ('booking_reminder', 'Booking Reminder'),
        ('booking_cancelled', 'Booking Cancelled'),
        ('purchase_confirmed', 'Purchase Confirmed'),
        ('assessment_ready', 'Assessment Ready'),
        ('package_expiring', 'Package Expiring Soon'),
        ('promotional', 'Promotional'),
        ('field_rental_request', 'Field Rental Request'),
        ('field_rental_approved', 'Field Rental Approved'),
        ('field_rental_rejected', 'Field Rental Rejected'),
        ('field_rental_cancelled', 'Field Rental Cancelled'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('read', 'Read'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    method = models.CharField(max_length=10, choices=NotificationPreference.NOTIFICATION_METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Optional references
    booking = models.ForeignKey('bookings.Booking', on_delete=models.SET_NULL, null=True, blank=True)
    package = models.ForeignKey('clients.ClientPackage', on_delete=models.SET_NULL, null=True, blank=True)

    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_notification_type_display()} - {self.client}"

    def send(self):
        """Send the notification based on method preference."""
        if self.method in ['email', 'both']:
            self._send_email()
        if self.method in ['sms', 'both']:
            self._send_sms()
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.save()

    def _send_email(self):
        """Send HTML email notification using the branded base template."""
        from django.core.mail import EmailMultiAlternatives
        from django.template.loader import render_to_string
        import html as _html
        try:
            to_email = self.client.user.email
            # Respect the universal opt-out — no email if this address unsubscribed.
            if EmailSuppression.is_suppressed(to_email):
                self.status = 'failed'
                self.save()
                return
            site_url = getattr(settings, 'SITE_URL', 'https://atletasperformancecenter.com')
            # Convert plain message text to simple HTML paragraphs
            body_html = ''.join(
                f'<p>{_html.escape(line)}</p>' if line.strip() else '<br>'
                for line in self.message.splitlines()
            )
            html_content = render_to_string('emails/base_email.html', {
                'subject':     self.title,
                'client_name': self.client.user.first_name or self.client.user.username,
                'content':     body_html,
                'site_url':    site_url,
                'current_year': timezone.now().year,
                'unsubscribe_url': make_unsubscribe_url(to_email, site_url),
            })
            msg = EmailMultiAlternatives(
                subject=self.title,
                body=self.message,  # plain text fallback
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[self.client.user.email],
            )
            msg.attach_alternative(html_content, 'text/html')
            msg.send()
        except Exception as e:
            self.status = 'failed'
            self.save()

    def _send_sms(self):
        """Send SMS notification - placeholder for Twilio/other integration."""
        # TODO: Integrate with Twilio or other SMS provider
        pass

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client', 'status']),
            models.Index(fields=['client', 'notification_type']),
            models.Index(fields=['status', 'read_at']),
            models.Index(fields=['booking']),
            models.Index(fields=['created_at']),
        ]


class NotificationTemplate(models.Model):
    """Reusable notification templates for automated messaging."""
    TEMPLATE_TYPE_CHOICES = [
        ('booking_confirmed', 'Booking Confirmed'),
        ('booking_reminder', 'Booking Reminder'),
        ('booking_cancelled', 'Booking Cancelled'),
        ('weekly_reminder', 'Weekly Session Reminder'),
        ('inactive_client', 'Inactive Client Re-engagement'),
        ('package_expiring', 'Package Expiring Soon'),
        ('package_exhausted', 'Package Sessions Exhausted'),
        ('assessment_ready', 'Assessment Ready'),
        ('upcoming_event', 'Upcoming Event'),
        ('custom_campaign', 'Custom Campaign'),
        ('promotional', 'Promotional'),
    ]

    name = models.CharField(max_length=100)
    template_type = models.CharField(max_length=30, choices=TEMPLATE_TYPE_CHOICES)
    description = models.TextField(blank=True, help_text="Internal description of this template")

    # Email content
    email_subject = models.CharField(max_length=200)
    email_body_html = models.TextField(help_text="HTML email body. Use {{variable}} for dynamic content.")
    email_body_text = models.TextField(help_text="Plain text email body for non-HTML clients.")

    # SMS content
    sms_body = models.CharField(max_length=160, blank=True, help_text="SMS message (160 char limit)")

    # Targeting (JSON filter criteria)
    target_filters = models.JSONField(
        default=dict,
        blank=True,
        help_text="Filter criteria: {'inactive_weeks': 3, 'has_package': true}"
    )

    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_template_type_display()})"

    def render_email_subject(self, context):
        """Render email subject with context variables."""
        from django.template import Template, Context
        template = Template(self.email_subject)
        return template.render(Context(context))

    def render_email_body_html(self, context):
        """Render HTML email body with context variables."""
        from django.template import Template, Context
        template = Template(self.email_body_html)
        return template.render(Context(context))

    def render_email_body_text(self, context):
        """Render plain text email body with context variables."""
        from django.template import Template, Context
        template = Template(self.email_body_text)
        return template.render(Context(context))

    def render_sms_body(self, context):
        """Render SMS body with context variables."""
        from django.template import Template, Context
        template = Template(self.sms_body)
        return template.render(Context(context))

    class Meta:
        ordering = ['template_type', 'name']
        verbose_name = 'Notification Template'
        verbose_name_plural = 'Notification Templates'


class PushSubscription(models.Model):
    """Web Push notification subscription for a client."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint = models.TextField(unique=True)
    p256dh_key = models.CharField(max_length=255)
    auth_key = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Push subscription for {self.client}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Push Subscription'
        verbose_name_plural = 'Push Subscriptions'


class NotificationSchedule(models.Model):
    """Schedule for custom notification campaigns."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    name = models.CharField(max_length=100)
    template = models.ForeignKey(NotificationTemplate, on_delete=models.CASCADE)
    scheduled_datetime = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    target_filters = models.JSONField(default=dict, blank=True)

    # Stats
    recipients_count = models.IntegerField(default=0)
    sent_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} - {self.get_status_display()}"

    class Meta:
        ordering = ['-scheduled_datetime']
        verbose_name = 'Notification Schedule'
        verbose_name_plural = 'Notification Schedules'


class NotificationOutbox(models.Model):
    """Short-lived buffer that coalesces related notification events into one email.

    A record is created the moment the first event fires (booking confirmed,
    payment received, package activated, etc.).  A Celery task is scheduled
    to run after `send_after`.  Any follow-on related events that arrive
    before the task fires simply append to `events` — so the task always
    sends ONE combined email regardless of how many individual events occurred.

    Records are deleted immediately after the email is sent.

    group_key format examples:
        "booking_42"   — all events for booking #42
        "pkg_17"       — events for ClientPackage #17
    """
    client     = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='outbox')
    group_key  = models.CharField(max_length=120, unique=True)
    events     = models.JSONField(default=list,
                     help_text="Accumulated list of {type, context, ts} dicts")
    send_after = models.DateTimeField(help_text="Task runs after this time")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['send_after'])]

    def __str__(self):
        types = ', '.join({e.get('type', '?') for e in self.events})
        return f'{self.group_key} [{types}] → {self.client}'
