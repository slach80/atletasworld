from django.db import models
from clients.models import Client
from coaches.models import Coach


class Program(models.Model):
    """Training programs offered."""
    name = models.CharField(max_length=200)
    description = models.TextField()
    duration_minutes = models.IntegerField(default=60)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    max_participants = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


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
    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='bookings')
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='bookings')
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True)
    google_event_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.client} - {self.program} on {self.scheduled_date}"

    class Meta:
        ordering = ['-scheduled_date', '-scheduled_time']
