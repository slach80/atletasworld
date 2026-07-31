from django.db import models
from django_prometheus.models import ExportModelOperationsMixin

from .core import Client


class Team(models.Model):
    """Soccer team managed by a coach client."""
    SKILL_LEVEL_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('elite', 'Elite/Competitive'),
    ]

    name = models.CharField(max_length=100, help_text='Team name (e.g., U14 Boys Elite)')
    slug = models.SlugField(max_length=100, unique=True)
    age_group = models.CharField(max_length=20, help_text='e.g., U10, U12, U14, U16, U19')
    skill_level = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, default='intermediate')
    club_name = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True, help_text='Team description and goals')
    max_players = models.IntegerField(default=18, help_text='Maximum number of players on team')

    # Relationships
    manager = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='managed_teams')
    coaches = models.ManyToManyField('coaches.Coach', related_name='teams', blank=True)

    is_select = models.BooleanField(default=False, help_text="APC Select team (2014, 2015, 2016, etc.)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.age_group})"

    @property
    def player_count(self):
        return self.players.filter(is_active=True).count()

    @property
    def active_players(self):
        return self.players.filter(is_active=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['manager', 'is_active']),
            models.Index(fields=['age_group']),
        ]


class RentalService(models.Model):
    """
    Service catalog entry — defines what can be rented (rooms, gym, partial/full field).
    Owner manages this catalog. Each FieldRentalSlot references one service.
    """
    SERVICE_TYPE_CHOICES = [
        ('field_full',    'Full Field'),
        ('field_partial', 'Partial Field'),
        ('room',          'Multi-Use Room'),
        ('gym',           'Gym'),
    ]
    PRICING_TYPE_CHOICES = [
        ('flat',   'Flat Rate'),
        ('hourly', 'Per Hour'),
    ]

    name          = models.CharField(max_length=200)
    service_type  = models.CharField(max_length=20, choices=SERVICE_TYPE_CHOICES)
    description   = models.TextField(blank=True)
    capacity      = models.IntegerField(null=True, blank=True, help_text='Max people (optional)')
    price         = models.DecimalField(max_digits=8, decimal_places=2,
                                        help_text='Default price shown to clients')
    pricing_type  = models.CharField(max_length=10, choices=PRICING_TYPE_CHOICES, default='flat')
    requires_approval = models.BooleanField(default=True,
                                            help_text='Requests need owner approval before confirming')
    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_service_type_display()})"

    class Meta:
        ordering = ['service_type', 'name']

    @property
    def type_icon(self):
        return {
            'field_full':    '⚽',
            'field_partial': '🟩',
            'room':          '🏠',
            'gym':           '🏋️',
        }.get(self.service_type, '📋')

    @property
    def price_display(self):
        suffix = '/hr' if self.pricing_type == 'hourly' else ''
        return f"${self.price}{suffix}"


class FieldRentalSlot(ExportModelOperationsMixin("field_rental_slot"), models.Model):
    """
    Owner-created rental slots. References a RentalService from the catalog.
    For field-type services, the field is exclusively reserved during the slot.
    """
    STATUS_CHOICES = [
        ('available',        'Available'),
        ('pending_approval', 'Pending Approval'),
        ('booked',           'Booked'),
        ('cancelled',        'Cancelled'),
    ]
    BOOKER_TYPE_CHOICES = [
        ('individual', 'Individual Client'),
        ('team',       'Team'),
    ]

    # Service catalog reference
    service          = models.ForeignKey(
        'RentalService', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='slots',
        help_text="Service from the catalog (room, gym, partial field, etc.)"
    )

    # Slot definition (owner-created)
    date             = models.DateField()
    start_time       = models.TimeField()
    end_time         = models.TimeField()
    duration_minutes = models.IntegerField(default=60)
    price            = models.DecimalField(max_digits=8, decimal_places=2)
    title            = models.CharField(max_length=200, blank=True,
                                        help_text="Optional label, e.g. 'Saturday Morning Full Field'")
    notes            = models.TextField(blank=True, help_text="Owner notes about this slot")
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')

    # Who requested it
    booked_by_client = models.ForeignKey(
        'Client', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='field_rentals'
    )
    booked_by_team   = models.ForeignKey(
        'Team', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='field_rentals'
    )
    booker_type      = models.CharField(max_length=20, choices=BOOKER_TYPE_CHOICES, null=True, blank=True)
    client_notes     = models.TextField(blank=True, help_text="Notes submitted with the request")
    requested_at     = models.DateTimeField(null=True, blank=True)

    # Approval tracking
    approved_at      = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    rejected_at      = models.DateTimeField(null=True, blank=True)

    # Payment
    payment_status = models.CharField(
        max_length=20,
        choices=[('pending', 'Pending'), ('paid', 'Paid'), ('refunded', 'Refunded')],
        default='pending'
    )
    amount_paid    = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    # Cancellation
    cancellation_notes = models.TextField(blank=True)
    cancelled_at       = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        label = self.title or "Field Rental"
        return f"{label} – {self.date} {self.start_time:%H:%M}–{self.end_time:%H:%M}"

    @property
    def is_available(self):
        return self.status == 'available'

    @property
    def requester_name(self):
        if self.booker_type == 'team' and self.booked_by_team:
            return self.booked_by_team.name
        if self.booked_by_client:
            return self.booked_by_client.user.get_full_name() or self.booked_by_client.user.username
        return '—'

    @property
    def has_conflicting_schedule_blocks(self):
        """True if any coach ScheduleBlock overlaps this time window."""
        from coaches.models import ScheduleBlock
        return ScheduleBlock.objects.filter(
            date=self.date,
            status__in=['available', 'booked']
        ).exclude(
            end_time__lte=self.start_time
        ).exclude(
            start_time__gte=self.end_time
        ).exists()

    def get_same_service_conflicts(self):
        """
        Return other FieldRentalSlots for the same service that overlap this
        time window and are pending_approval or booked.
        Returns empty queryset if this slot has no service assigned.
        """
        if not self.service_id:
            return FieldRentalSlot.objects.none()
        return FieldRentalSlot.objects.filter(
            service_id=self.service_id,
            date=self.date,
            status__in=['pending_approval', 'booked'],
        ).exclude(pk=self.pk).exclude(
            end_time__lte=self.start_time
        ).exclude(
            start_time__gte=self.end_time
        )

    @classmethod
    def check_field_blocked(cls, date, start_time, end_time):
        """Returns True if a booked or pending_approval slot blocks this window."""
        return cls.objects.filter(
            date=date,
            status__in=['booked', 'pending_approval']
        ).exclude(
            end_time__lte=start_time
        ).exclude(
            start_time__gte=end_time
        ).exists()

    @classmethod
    def check_service_blocked(cls, service_id, date, start_time, end_time, exclude_pk=None):
        """
        Return queryset of conflicting slots for the given service at the
        specified date/time window (pending_approval or booked).
        """
        qs = cls.objects.filter(
            service_id=service_id,
            date=date,
            status__in=['pending_approval', 'booked'],
        ).exclude(
            end_time__lte=start_time
        ).exclude(
            start_time__gte=end_time
        )
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        return qs

    class Meta:
        ordering = ['date', 'start_time']
        indexes = [
            models.Index(fields=['date', 'status']),
            models.Index(fields=['status', 'date']),
            models.Index(fields=['approved_at']),
        ]
