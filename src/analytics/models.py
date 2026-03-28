from django.db import models


class DailyMetrics(models.Model):
    """Daily aggregated business metrics."""
    date = models.DateField(unique=True)
    total_bookings = models.IntegerField(default=0)
    completed_sessions = models.IntegerField(default=0)
    cancelled_sessions = models.IntegerField(default=0)
    new_clients = models.IntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Metrics for {self.date}"

    class Meta:
        verbose_name_plural = 'Daily metrics'
        ordering = ['-date']
