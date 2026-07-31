from django.db import models
from clients.models import Client
from bookings.models import Booking


class ProcessedWebhookEvent(models.Model):
    """Deduplication table for Stripe webhook events — prevents double-processing on retries."""
    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['processed_at'])]

    def __str__(self):
        return f'{self.event_type} — {self.event_id}'


class Payment(models.Model):
    """Payment records via Stripe."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='payments')
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    stripe_payment_intent_id = models.CharField(max_length=255, unique=True)
    stripe_charge_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"${self.amount} - {self.client} ({self.status})"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]
