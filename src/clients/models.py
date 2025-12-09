from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings


class Client(models.Model):
    """Client profile for parents/guardians."""
    CLIENT_TYPE_CHOICES = [
        ('parent', 'Parent/Guardian'),
        ('coach', 'Team Coach'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    client_type = models.CharField(max_length=10, choices=CLIENT_TYPE_CHOICES, default='parent')
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    emergency_contact = models.CharField(max_length=100, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username}"

    class Meta:
        ordering = ['-created_at']


class Player(models.Model):
    """Player profile for children/athletes."""
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other/Prefer not to say'),
    ]

    SKILL_LEVEL_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('elite', 'Elite/Competitive'),
    ]

    POSITION_CHOICES = [
        ('goalkeeper', 'Goalkeeper'),
        ('defender', 'Defender'),
        ('midfielder', 'Midfielder'),
        ('forward', 'Forward'),
        ('multiple', 'Multiple Positions'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='players')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    birth_year = models.IntegerField()
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    soccer_club = models.CharField(max_length=100, blank=True, help_text="Current soccer club")
    team_name = models.CharField(max_length=100, blank=True, help_text="Team name (e.g., U14 Boys)")
    skill_level = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, default='beginner')
    primary_position = models.CharField(max_length=20, choices=POSITION_CHOICES, blank=True)
    notes = models.TextField(blank=True, help_text="Any special needs or notes")
    photo = models.ImageField(upload_to='players/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.birth_year})"

    @property
    def age(self):
        return timezone.now().year - self.birth_year

    @property
    def age_group(self):
        """Returns age group like U10, U12, etc."""
        age = self.age
        if age <= 6:
            return 'U6'
        elif age <= 8:
            return 'U8'
        elif age <= 10:
            return 'U10'
        elif age <= 12:
            return 'U12'
        elif age <= 14:
            return 'U14'
        elif age <= 16:
            return 'U16'
        elif age <= 19:
            return 'U19'
        else:
            return 'Adult'

    class Meta:
        ordering = ['first_name', 'last_name']


class Package(models.Model):
    """Package types available for purchase."""
    PACKAGE_TYPE_CHOICES = [
        ('basic4', 'Basic 4 - 4 classes / 4 weeks'),
        ('basic8', 'Basic 8 - 8 classes / 4 weeks'),
        ('elite24', 'Elite 24 - 24 classes / 12 weeks'),
        ('unlimited', 'Unlimited - 12 weeks'),
        ('special', 'Special Event Package'),
        ('team', 'Team Training Package'),
    ]

    name = models.CharField(max_length=100)
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPE_CHOICES)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    sessions_included = models.IntegerField(help_text="Number of sessions included, 0 for unlimited")
    validity_weeks = models.IntegerField(help_text="How many weeks the package is valid")
    is_active = models.BooleanField(default=True)

    # Special package fields
    is_special = models.BooleanField(default=False, help_text="Mark as special event package")
    event_start_date = models.DateField(null=True, blank=True, help_text="Start date for special event")
    event_end_date = models.DateField(null=True, blank=True, help_text="End date for special event")
    event_location = models.CharField(max_length=200, blank=True, help_text="Location for special event")
    max_participants = models.IntegerField(default=0, help_text="Max participants, 0 for unlimited")
    age_group = models.CharField(max_length=50, blank=True, help_text="Target age group (e.g., U13, U15)")

    def __str__(self):
        return f"{self.name} - ${self.price}"

    @property
    def is_event_package(self):
        """Check if this is a special event package with dates."""
        return self.is_special and self.event_start_date and self.event_end_date

    @property
    def spots_remaining(self):
        """Calculate remaining spots for special packages."""
        if self.max_participants == 0:
            return None  # Unlimited
        purchased = ClientPackage.objects.filter(
            package=self,
            status__in=['active', 'exhausted']
        ).count()
        return max(0, self.max_participants - purchased)

    class Meta:
        ordering = ['price']


class ClientPackage(models.Model):
    """Tracks packages purchased by clients."""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('exhausted', 'Sessions Exhausted'),
        ('cancelled', 'Cancelled'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='packages')
    package = models.ForeignKey(Package, on_delete=models.PROTECT)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='packages', null=True, blank=True,
                               help_text="Optional: assign package to specific player")
    purchase_date = models.DateTimeField(auto_now_add=True)
    start_date = models.DateField()
    expiry_date = models.DateField()
    sessions_remaining = models.IntegerField()
    sessions_used = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    stripe_payment_id = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.client} - {self.package.name} ({self.status})"

    @property
    def is_valid(self):
        """Check if package is still valid for booking."""
        if self.status != 'active':
            return False
        if self.expiry_date < timezone.now().date():
            return False
        if self.package.sessions_included > 0 and self.sessions_remaining <= 0:
            return False
        return True

    def use_session(self):
        """Decrement session count when a booking is made."""
        if self.package.sessions_included > 0:
            self.sessions_remaining -= 1
            self.sessions_used += 1
            if self.sessions_remaining <= 0:
                self.status = 'exhausted'
            self.save()

    def calculate_upgrade_cost(self, new_package):
        """Calculate upgrade cost based on remaining sessions."""
        if not self.is_valid:
            return new_package.price  # Full price if current package invalid

        # Calculate value of remaining sessions
        if self.package.sessions_included > 0:
            price_per_session = self.package.price / self.package.sessions_included
            remaining_value = price_per_session * self.sessions_remaining
        else:
            # For unlimited, prorate by time remaining
            from datetime import date
            total_days = (self.expiry_date - self.start_date).days
            remaining_days = (self.expiry_date - date.today()).days
            if remaining_days > 0 and total_days > 0:
                remaining_value = (self.package.price * remaining_days) / total_days
            else:
                remaining_value = 0

        upgrade_cost = max(0, float(new_package.price) - float(remaining_value))
        return round(upgrade_cost, 2)

    def get_upgrade_options(self):
        """Get available upgrade packages with calculated costs."""
        from decimal import Decimal
        upgrades = []
        available_packages = Package.objects.filter(
            is_active=True,
            price__gt=self.package.price
        ).order_by('price')

        for pkg in available_packages:
            upgrades.append({
                'package': pkg,
                'upgrade_cost': self.calculate_upgrade_cost(pkg),
                'sessions_gained': pkg.sessions_included - self.sessions_remaining if pkg.sessions_included > 0 else 'Unlimited',
            })
        return upgrades

    class Meta:
        ordering = ['-purchase_date']


class SessionReservation(models.Model):
    """Temporary reservation to hold spots during booking process."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='reservations')
    schedule_block = models.ForeignKey('coaches.ScheduleBlock', on_delete=models.CASCADE, related_name='reservations')
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_confirmed = models.BooleanField(default=False)

    def __str__(self):
        return f"Reservation: {self.player} - {self.schedule_block}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at and not self.is_confirmed

    @classmethod
    def cleanup_expired(cls):
        """Remove expired reservations and free up spots."""
        expired = cls.objects.filter(
            expires_at__lt=timezone.now(),
            is_confirmed=False
        )
        for reservation in expired:
            # Decrement the participant count
            block = reservation.schedule_block
            if block.current_participants > 0:
                block.current_participants -= 1
                block.save()
        expired.delete()

    class Meta:
        ordering = ['-created_at']


class BookingPreference(models.Model):
    """Client booking preferences for favorite coaches and times."""
    TIME_SLOT_CHOICES = [
        ('morning', 'Morning (6am-12pm)'),
        ('afternoon', 'Afternoon (12pm-5pm)'),
        ('evening', 'Evening (5pm-9pm)'),
    ]

    DAY_CHOICES = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ]

    client = models.OneToOneField(Client, on_delete=models.CASCADE, related_name='booking_preferences')
    favorite_coaches = models.ManyToManyField('coaches.Coach', blank=True, related_name='favorited_by')
    preferred_days = models.JSONField(default=list, blank=True, help_text="List of preferred days")
    preferred_time_slots = models.JSONField(default=list, blank=True, help_text="List of preferred time slots")
    auto_filter = models.BooleanField(default=False, help_text="Automatically filter sessions by preferences")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Booking preferences for {self.client}"

    def matches_block(self, schedule_block):
        """Check if a schedule block matches client preferences."""
        # Check coach preference
        if self.favorite_coaches.exists():
            if schedule_block.coach not in self.favorite_coaches.all():
                return False

        # Check day preference
        if self.preferred_days:
            day_name = schedule_block.date.strftime('%A').lower()
            if day_name not in self.preferred_days:
                return False

        # Check time slot preference
        if self.preferred_time_slots:
            hour = schedule_block.start_time.hour
            if hour < 12:
                slot = 'morning'
            elif hour < 17:
                slot = 'afternoon'
            else:
                slot = 'evening'
            if slot not in self.preferred_time_slots:
                return False

        return True


class NotificationPreference(models.Model):
    """Client notification preferences."""
    NOTIFICATION_METHOD_CHOICES = [
        ('email', 'Email'),
        ('sms', 'SMS Text Message'),
        ('both', 'Email and SMS'),
        ('none', 'No Notifications'),
    ]

    client = models.OneToOneField(Client, on_delete=models.CASCADE, related_name='notification_preferences')

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
    package = models.ForeignKey(ClientPackage, on_delete=models.SET_NULL, null=True, blank=True)

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
        """Send email notification."""
        try:
            send_mail(
                subject=self.title,
                message=self.message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[self.client.user.email],
                fail_silently=False,
            )
        except Exception as e:
            self.status = 'failed'
            self.save()

    def _send_sms(self):
        """Send SMS notification - placeholder for Twilio/other integration."""
        # TODO: Integrate with Twilio or other SMS provider
        pass

    class Meta:
        ordering = ['-created_at']


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
