from django.db import models
from clients.models import Client, Player, ClientPackage
from coaches.models import Coach


class Program(models.Model):
    """Training programs offered."""
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
    requires_package = models.BooleanField(default=False, help_text="Requires active package to book")
    min_age = models.IntegerField(null=True, blank=True, help_text="Minimum age for this program")
    max_age = models.IntegerField(null=True, blank=True, help_text="Maximum age for this program")
    skill_levels = models.CharField(max_length=100, blank=True,
                                    help_text="Comma-separated skill levels: beginner,intermediate,advanced,elite")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def is_suitable_for_player(self, player):
        """Check if program is suitable for a given player."""
        # Check age requirements
        if self.min_age and player.age < self.min_age:
            return False
        if self.max_age and player.age > self.max_age:
            return False
        # Check skill level
        if self.skill_levels:
            allowed_levels = [s.strip() for s in self.skill_levels.split(',')]
            if player.skill_level not in allowed_levels:
                return False
        return True


class Session(models.Model):
    """Available session slots for booking."""
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


class Booking(models.Model):
    """Session bookings."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='bookings')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='bookings',
                               null=True, blank=True, help_text="The player attending the session")
    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='bookings')
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='bookings')
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='bookings',
                                null=True, blank=True)
    client_package = models.ForeignKey(ClientPackage, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='bookings', help_text="Package used for this booking")
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_status = models.CharField(max_length=20, default='pending',
                                      choices=[('pending', 'Pending'), ('paid', 'Paid'),
                                               ('package', 'Package'), ('refunded', 'Refunded')])
    amount_paid = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    google_event_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.player} - {self.program} on {self.scheduled_date}"

    def save(self, *args, **kwargs):
        # Decrement session spots on new booking
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and self.session and self.status == 'confirmed':
            self.session.spots_remaining -= 1
            self.session.save()

    class Meta:
        ordering = ['-scheduled_date', '-scheduled_time']
