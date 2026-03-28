from django.db import models
from clients.models import Client
from coaches.models import Coach
from bookings.models import Booking


class Review(models.Model):
    """Client reviews and ratings."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='reviews')
    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='reviews')
    booking = models.OneToOneField(Booking, on_delete=models.SET_NULL, null=True, blank=True)
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    comment = models.TextField(blank=True)
    is_featured = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.client} - {self.rating} stars for {self.coach}"

    class Meta:
        ordering = ['-created_at']
