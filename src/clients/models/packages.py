from django.db import models, transaction
from django.db.models import F
from django.utils import timezone
from django_prometheus.models import ExportModelOperationsMixin

from .core import Client, Player


class Package(models.Model):
    """Package types available for purchase."""
    PACKAGE_TYPE_CHOICES = [
        ('basic4', 'Basic 4 - 4 classes / 4 weeks'),
        ('basic8', 'Basic 8 - 8 classes / 4 weeks'),
        ('elite24', 'Elite 24 - 24 classes / 12 weeks'),
        ('unlimited', 'Unlimited - 12 weeks'),
        ('special', 'Special Event Package'),
        ('team', 'Team Training Package'),
        ('select', 'APC Select Membership'),
    ]

    name = models.CharField(max_length=100)
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPE_CHOICES)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    stripe_price_id = models.CharField(max_length=100, blank=True,
                                        help_text="Stripe Price ID for recurring packages (price_xxx)")
    sessions_included = models.IntegerField(help_text="Number of sessions included, 0 for unlimited")
    validity_weeks = models.IntegerField(help_text="How many weeks the package is valid")
    is_active      = models.BooleanField(default=True)
    is_purchasable = models.BooleanField(
        default=True,
        help_text='Uncheck to hide from new purchases while keeping existing client packages active'
    )

    # Special package fields
    is_special = models.BooleanField(default=False, help_text="Mark as special event package")
    event_start_date = models.DateField(null=True, blank=True, help_text="Start date for special event")
    event_start_time = models.TimeField(null=True, blank=True, help_text="Start time for special event")
    event_end_date = models.DateField(null=True, blank=True, help_text="End date for special event")
    event_end_time = models.TimeField(null=True, blank=True, help_text="End time for special event")
    event_location = models.CharField(max_length=200, blank=True, help_text="Location for special event")
    max_participants = models.IntegerField(default=0, help_text="Max participants, 0 for unlimited")
    age_group = models.CharField(max_length=50, blank=True, help_text="Target age group (e.g., U13, U15)")

    BILLING_TIER_CHOICES = [
        ('monthly', 'Monthly'),
        ('thirds',  'Every 4 Months (Thirds)'),
        ('half',    'Every 3 Months (Half)'),
        ('full',    'Annual (Full Year)'),
    ]
    billing_tier = models.CharField(
        max_length=20, choices=BILLING_TIER_CHOICES, blank=True, default='',
        help_text="Billing interval for Select membership tiers. Leave blank for one-time packages."
    )
    program_group = models.CharField(
        max_length=100, blank=True, default='',
        help_text="Groups packages into a single card with billing picker (e.g. 'Elite 24 Fall')"
    )

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
        indexes = [
            models.Index(fields=['is_active', 'is_special']),
            models.Index(fields=['event_start_date', 'event_end_date']),
        ]


class ClientPackage(ExportModelOperationsMixin("client_package"), models.Model):
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
    stripe_payment_id = models.CharField(max_length=100, blank=True, db_index=True,
                                          help_text="Stripe PaymentIntent ID for one-time purchase")
    stripe_subscription_id = models.CharField(max_length=100, blank=True, db_index=True,
                                               help_text="Stripe Subscription ID for recurring packages")
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.client} - {self.package.name} ({self.status})"

    @property
    def is_valid(self):
        """Check if package is still valid for booking."""
        if self.status != 'active':
            return False
        if self.expiry_date < timezone.localdate():
            return False
        if self.package.sessions_included > 0 and self.sessions_remaining <= 0:
            return False
        return True

    def use_session(self):
        """Consume one session from this package when a booking is confirmed.

        Uses a conditional atomic update to prevent concurrent over-decrement.
        Returns True if a session was consumed, False if none remained.
        Unlimited packages (sessions_included == 0) always return True.
        """
        if self.package.sessions_included == 0:
            return True

        with transaction.atomic():
            updated = ClientPackage.objects.filter(
                pk=self.pk, sessions_remaining__gt=0
            ).update(
                sessions_remaining=F('sessions_remaining') - 1,
                sessions_used=F('sessions_used') + 1,
            )
            if not updated:
                return False
            # Reload to check if now exhausted
            self.refresh_from_db(fields=['sessions_remaining', 'sessions_used'])
            if self.sessions_remaining <= 0:
                ClientPackage.objects.filter(pk=self.pk, status='active').update(status='exhausted')
                self.status = 'exhausted'
        return True

    def calculate_upgrade_cost(self, new_package):
        """Calculate how much a client owes to upgrade to a higher-tier package.

        The upgrade is prorated: the unused value of the current package is
        credited against the new package's price.

        For session-counted packages:
            remaining_value = (price / total_sessions) × sessions_remaining

        For unlimited (time-based) packages:
            remaining_value = price × (days_left / total_days)

        Args:
            new_package (Package): The package the client wants to upgrade to.

        Returns:
            Decimal: The amount (≥ 0) the client must pay.  Returns the full
                     new_package.price if the current package is no longer valid.
        """
        from decimal import Decimal, ROUND_HALF_UP

        def to_decimal(value):
            return value if isinstance(value, Decimal) else Decimal(str(value))

        new_price = to_decimal(new_package.price)

        if not self.is_valid:
            return new_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)  # Full price if current package invalid

        current_price = to_decimal(self.package.price)

        # Calculate value of remaining sessions
        if self.package.sessions_included > 0:
            price_per_session = current_price / self.package.sessions_included
            remaining_value = price_per_session * self.sessions_remaining
        else:
            # For unlimited packages, prorate by days remaining in the term
            total_days = (self.expiry_date - self.start_date).days
            remaining_days = (self.expiry_date - timezone.localdate()).days
            if remaining_days > 0 and total_days > 0:
                remaining_value = (current_price * remaining_days) / total_days
            else:
                remaining_value = Decimal('0')

        upgrade_cost = max(Decimal('0'), new_price - remaining_value)
        return upgrade_cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

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
        indexes = [
            models.Index(fields=['client', 'status']),
            models.Index(fields=['client', 'expiry_date']),
            models.Index(fields=['status', 'expiry_date']),
            models.Index(fields=['purchase_date']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(sessions_remaining__gte=0),
                name='clientpackage_sessions_remaining_non_negative',
            ),
        ]


class ClientCredit(models.Model):
    """
    Tracks monetary credits for clients.
    APC Select members receive $40/month auto-credited toward APC Training packages.
    Owner can also grant manual credits.
    """
    CREDIT_TYPE_CHOICES = [
        ('select_monthly', 'APC Select Monthly Credit'),
        ('manual', 'Manual Grant'),
        ('referral', 'Referral Credit'),
    ]
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('applied', 'Applied'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='credits')
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    credit_type = models.CharField(max_length=20, choices=CREDIT_TYPE_CHOICES, default='manual')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='available')

    # For select_monthly credits — which Select ClientPackage generated this
    source_package = models.ForeignKey(
        'ClientPackage', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='granted_credits',
        help_text='The APC Select ClientPackage that generated this credit'
    )
    # Which player this credit is attributed to, snapshotted at grant time.
    # Deliberately independent of source_package.player — if the package is later
    # reassigned to a different player, this credit's attribution does not follow it.
    player = models.ForeignKey(
        'Player', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='credits',
        help_text='Player this credit is attributed to (set at creation, not inferred from the package)'
    )
    # For referral credits — which Referral generated this
    referral = models.ForeignKey(
        'clients.Referral', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='credits',
        help_text='The Referral that generated this credit'
    )
    # What package purchase this was applied toward
    applied_to = models.ForeignKey(
        'ClientPackage', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='applied_credits',
        help_text='The ClientPackage this credit was applied against'
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True, help_text='Leave blank for no expiry')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='granted_credits'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.client} — ${self.amount} ({self.get_credit_type_display()}) [{self.status}]"

    @property
    def is_usable(self):
        from django.utils import timezone
        if self.status != 'available':
            return False
        if self.expires_at and self.expires_at < timezone.localdate():
            return False
        return True

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client', 'status']),
            models.Index(fields=['status', 'expires_at']),
        ]


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
        indexes = [
            models.Index(fields=['client', 'schedule_block']),
            models.Index(fields=['client', 'is_confirmed']),
            models.Index(fields=['expires_at', 'is_confirmed']),
        ]


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
