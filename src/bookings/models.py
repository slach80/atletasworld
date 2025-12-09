from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from clients.models import Client, Player, ClientPackage
from coaches.models import Coach


class SessionType(models.Model):
    """Defines types of training sessions available."""
    SESSION_FORMAT_CHOICES = [
        ('private', 'Private (1-on-1)'),
        ('semi_private', 'Semi-Private (2-3 players)'),
        ('group', 'Group Session'),
        ('clinic', 'Clinic/Camp'),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    session_format = models.CharField(max_length=20, choices=SESSION_FORMAT_CHOICES, default='private')
    duration_minutes = models.IntegerField(default=60)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    max_participants = models.IntegerField(default=1)
    color = models.CharField(max_length=7, default='#2ecc71', help_text="Hex color for calendar display")
    is_active = models.BooleanField(default=True)
    requires_package = models.BooleanField(default=False, help_text="Requires active package to book")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.duration_minutes}min - ${self.price})"

    class Meta:
        ordering = ['name']


class AvailabilitySlot(models.Model):
    """Coach availability slots - can be one-time or recurring."""
    RECURRENCE_CHOICES = [
        ('none', 'One-time'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-weekly'),
    ]

    STATUS_CHOICES = [
        ('available', 'Available'),
        ('partially_booked', 'Partially Booked'),
        ('fully_booked', 'Fully Booked'),
        ('cancelled', 'Cancelled'),
    ]

    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='availability_slots')
    session_type = models.ForeignKey(SessionType, on_delete=models.CASCADE, related_name='availability_slots')

    # Date/Time
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    # Recurrence
    recurrence = models.CharField(max_length=20, choices=RECURRENCE_CHOICES, default='none')
    recurrence_end_date = models.DateField(null=True, blank=True, help_text="End date for recurring slots")
    parent_slot = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                                    related_name='recurring_instances', help_text="Parent slot for recurring series")

    # Capacity
    max_bookings = models.IntegerField(default=1)
    current_bookings = models.IntegerField(default=0)

    # Status & Pricing
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    price_override = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True,
                                         help_text="Override session type price if set")
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.coach} - {self.date} {self.start_time}-{self.end_time}"

    @property
    def is_available(self):
        """Check if slot has available spots."""
        return self.status in ['available', 'partially_booked'] and self.spots_remaining > 0

    @property
    def spots_remaining(self):
        return max(0, self.max_bookings - self.current_bookings)

    @property
    def effective_price(self):
        """Get the price for this slot."""
        return self.price_override if self.price_override else self.session_type.price

    @property
    def datetime_start(self):
        """Get combined datetime for start."""
        from datetime import datetime
        return datetime.combine(self.date, self.start_time)

    @property
    def datetime_end(self):
        """Get combined datetime for end."""
        from datetime import datetime
        return datetime.combine(self.date, self.end_time)

    def check_conflicts(self, exclude_self=True):
        """Check for overlapping slots with same coach."""
        conflicts = AvailabilitySlot.objects.filter(
            coach=self.coach,
            date=self.date,
            status__in=['available', 'partially_booked', 'fully_booked']
        ).exclude(
            end_time__lte=self.start_time
        ).exclude(
            start_time__gte=self.end_time
        )

        if exclude_self and self.pk:
            conflicts = conflicts.exclude(pk=self.pk)

        return conflicts.exists()

    def update_status(self):
        """Update slot status based on bookings."""
        if self.current_bookings >= self.max_bookings:
            self.status = 'fully_booked'
        elif self.current_bookings > 0:
            self.status = 'partially_booked'
        else:
            self.status = 'available'
        self.save(update_fields=['status'])

    def generate_recurring_slots(self):
        """Generate individual slot instances from recurring pattern."""
        if self.recurrence == 'none' or not self.recurrence_end_date:
            return []

        slots = []
        current_date = self.date + timedelta(days=7 if self.recurrence == 'weekly' else
                                              14 if self.recurrence == 'biweekly' else 1)

        while current_date <= self.recurrence_end_date:
            slot = AvailabilitySlot(
                coach=self.coach,
                session_type=self.session_type,
                date=current_date,
                start_time=self.start_time,
                end_time=self.end_time,
                recurrence='none',
                max_bookings=self.max_bookings,
                price_override=self.price_override,
                parent_slot=self,
            )
            slots.append(slot)

            if self.recurrence == 'daily':
                current_date += timedelta(days=1)
            elif self.recurrence == 'weekly':
                current_date += timedelta(days=7)
            elif self.recurrence == 'biweekly':
                current_date += timedelta(days=14)

        return slots

    def clean(self):
        """Validate slot data."""
        if self.start_time >= self.end_time:
            raise ValidationError("End time must be after start time.")

        if self.check_conflicts():
            raise ValidationError("This slot conflicts with an existing slot.")

    class Meta:
        ordering = ['date', 'start_time']
        unique_together = ['coach', 'date', 'start_time']


class Booking(models.Model):
    """Session bookings with full lifecycle management."""
    STATUS_CHOICES = [
        ('pending', 'Pending Confirmation'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
        ('rescheduled', 'Rescheduled'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('package', 'Package Used'),
        ('refunded', 'Refunded'),
        ('partial_refund', 'Partial Refund'),
    ]

    CANCELLATION_REASON_CHOICES = [
        ('client_request', 'Client Request'),
        ('coach_unavailable', 'Coach Unavailable'),
        ('weather', 'Weather'),
        ('illness', 'Illness'),
        ('emergency', 'Emergency'),
        ('rescheduled', 'Rescheduled to Another Time'),
        ('other', 'Other'),
    ]

    # Core relationships
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='bookings')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='bookings',
                               null=True, blank=True, help_text="The player attending the session")
    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='bookings')
    availability_slot = models.ForeignKey(AvailabilitySlot, on_delete=models.SET_NULL,
                                          null=True, blank=True, related_name='bookings')
    session_type = models.ForeignKey(SessionType, on_delete=models.CASCADE, related_name='bookings',
                                     null=True, blank=True)  # Nullable for migration from legacy Program

    # Package tracking
    client_package = models.ForeignKey(ClientPackage, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='bookings', help_text="Package used for this booking")

    # Schedule
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    duration_minutes = models.IntegerField(default=60)

    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    amount_paid = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    # Cancellation/Rescheduling
    cancellation_reason = models.CharField(max_length=20, choices=CANCELLATION_REASON_CHOICES,
                                           blank=True, null=True)
    cancellation_notes = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='cancelled_bookings')
    rescheduled_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='rescheduled_to')

    # Calendar integration
    google_event_id = models.CharField(max_length=255, blank=True)
    calendar_synced = models.BooleanField(default=False)

    # Notes
    client_notes = models.TextField(blank=True, help_text="Notes from client")
    coach_notes = models.TextField(blank=True, help_text="Private notes from coach")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        player_name = self.player.first_name if self.player else "No player"
        return f"{player_name} - {self.session_type.name} on {self.scheduled_date}"

    @property
    def scheduled_datetime(self):
        from datetime import datetime
        return datetime.combine(self.scheduled_date, self.scheduled_time)

    @property
    def can_cancel(self):
        """Check if booking can still be cancelled (24 hours before)."""
        if self.status in ['cancelled', 'completed', 'no_show']:
            return False
        hours_until = (self.scheduled_datetime - timezone.now()).total_seconds() / 3600
        return hours_until >= 24

    @property
    def can_reschedule(self):
        """Check if booking can be rescheduled."""
        return self.can_cancel and self.status in ['pending', 'confirmed']

    def confirm(self, user=None):
        """Confirm the booking."""
        if self.status != 'pending':
            raise ValidationError("Only pending bookings can be confirmed.")

        self.status = 'confirmed'
        self.confirmed_at = timezone.now()
        self.save()

        # Update slot booking count
        if self.availability_slot:
            self.availability_slot.current_bookings += 1
            self.availability_slot.update_status()

        return True

    def cancel(self, reason, notes='', cancelled_by=None):
        """Cancel the booking with reason tracking."""
        if not self.can_cancel:
            raise ValidationError("This booking cannot be cancelled.")

        self.status = 'cancelled'
        self.cancellation_reason = reason
        self.cancellation_notes = notes
        self.cancelled_at = timezone.now()
        self.cancelled_by = cancelled_by
        self.save()

        # Update slot booking count
        if self.availability_slot and self.availability_slot.current_bookings > 0:
            self.availability_slot.current_bookings -= 1
            self.availability_slot.update_status()

        # Return session to package if applicable
        if self.client_package and self.payment_status == 'package':
            self.client_package.sessions_remaining += 1
            self.client_package.sessions_used -= 1
            self.client_package.save()

        return True

    def reschedule(self, new_slot, cancelled_by=None):
        """Reschedule booking to a new slot."""
        if not self.can_reschedule:
            raise ValidationError("This booking cannot be rescheduled.")

        # Create new booking
        new_booking = Booking.objects.create(
            client=self.client,
            player=self.player,
            coach=new_slot.coach,
            availability_slot=new_slot,
            session_type=self.session_type,
            client_package=self.client_package,
            scheduled_date=new_slot.date,
            scheduled_time=new_slot.start_time,
            duration_minutes=self.duration_minutes,
            status='confirmed',
            payment_status=self.payment_status,
            amount_paid=self.amount_paid,
            rescheduled_from=self,
            client_notes=self.client_notes,
        )

        # Cancel old booking
        self.cancel(reason='rescheduled', notes=f'Rescheduled to {new_slot.date}', cancelled_by=cancelled_by)

        return new_booking

    def complete(self):
        """Mark booking as completed."""
        if self.status != 'confirmed':
            raise ValidationError("Only confirmed bookings can be completed.")

        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save()
        return True

    def mark_no_show(self):
        """Mark booking as no-show."""
        if self.status != 'confirmed':
            raise ValidationError("Only confirmed bookings can be marked as no-show.")

        self.status = 'no_show'
        self.save()
        return True

    def use_package(self, package):
        """Use a session from client package."""
        if package.sessions_remaining <= 0:
            raise ValidationError("No sessions remaining in package.")

        if not package.is_valid:
            raise ValidationError("Package is expired or inactive.")

        self.client_package = package
        self.payment_status = 'package'
        package.sessions_remaining -= 1
        package.sessions_used += 1
        package.save()
        self.save()
        return True

    def clean(self):
        """Validate booking data."""
        # Check for double booking (same client, same time)
        conflicts = Booking.objects.filter(
            client=self.client,
            scheduled_date=self.scheduled_date,
            status__in=['pending', 'confirmed']
        ).exclude(pk=self.pk)

        for booking in conflicts:
            # Check time overlap
            if not (self.scheduled_time >= booking.scheduled_time or
                    self.scheduled_time <= booking.scheduled_time):
                raise ValidationError("Client already has a booking at this time.")

    class Meta:
        ordering = ['-scheduled_date', '-scheduled_time']


# Keep Program model for backward compatibility but mark as deprecated
class Program(models.Model):
    """DEPRECATED: Use SessionType instead. Kept for migration compatibility."""
    PROGRAM_TYPE_CHOICES = [
        ('drop_in', 'Drop-in (Pay per session)'),
        ('package', 'Package Required'),
        ('event', 'Special Event'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField()
    duration_minutes = models.IntegerField(default=60)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    max_participants = models.IntegerField(default=1)
    program_type = models.CharField(max_length=20, choices=PROGRAM_TYPE_CHOICES, default='drop_in')
    requires_package = models.BooleanField(default=False)
    min_age = models.IntegerField(null=True, blank=True)
    max_age = models.IntegerField(null=True, blank=True)
    skill_levels = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Link to new SessionType for migration
    session_type = models.ForeignKey(SessionType, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='legacy_programs')

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Session(models.Model):
    """DEPRECATED: Use AvailabilitySlot instead."""
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='sessions')
    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='sessions')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    spots_total = models.IntegerField(default=20)
    spots_remaining = models.IntegerField(default=20)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.program.name} - {self.date} {self.start_time}"

    class Meta:
        ordering = ['date', 'start_time']
        unique_together = ['program', 'coach', 'date', 'start_time']
