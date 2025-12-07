from django.db import models
from django.contrib.auth.models import User


class Coach(models.Model):
    """Coach profile with availability and specializations."""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    photo = models.ImageField(upload_to='coaches/', blank=True, null=True)
    specializations = models.TextField(blank=True, help_text="Comma-separated list")
    certifications = models.TextField(blank=True)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    google_calendar_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Coach {self.user.get_full_name() or self.user.username}"

    class Meta:
        ordering = ['user__first_name']


class Availability(models.Model):
    """Coach availability schedule."""
    DAYS_OF_WEEK = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='availabilities')
    day_of_week = models.IntegerField(choices=DAYS_OF_WEEK)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'Availabilities'
        ordering = ['day_of_week', 'start_time']
