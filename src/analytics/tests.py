"""
Unit tests for the analytics app.

Covers:
  - DailyMetrics: model creation, str representation, default values, date uniqueness
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from django.db import IntegrityError

from analytics.models import DailyMetrics


@pytest.mark.unit
class TestDailyMetricsModel:
    """Tests for the DailyMetrics model (daily aggregated business metrics)."""

    def test_str_representation(self, daily_metrics):
        """__str__ should include the date so records are easy to identify in admin."""
        result = str(daily_metrics)
        assert str(daily_metrics.date) in result

    def test_default_values_are_zero(self, db):
        """A newly created DailyMetrics with no data should have all numeric defaults at 0."""
        metrics = DailyMetrics.objects.create(date=date.today() - timedelta(days=10))
        assert metrics.total_bookings == 0
        assert metrics.completed_sessions == 0
        assert metrics.cancelled_sessions == 0
        assert metrics.new_clients == 0
        assert metrics.total_revenue == Decimal('0')

    def test_date_field_is_unique(self, daily_metrics):
        """Creating a second DailyMetrics for the same date should raise IntegrityError."""
        with pytest.raises(IntegrityError):
            DailyMetrics.objects.create(date=daily_metrics.date)

    def test_ordering_by_date_descending(self, db):
        """DailyMetrics should be ordered by most recent date first."""
        today = date.today()
        older = DailyMetrics.objects.create(date=today - timedelta(days=5))
        newer = DailyMetrics.objects.create(date=today - timedelta(days=1))
        records = list(DailyMetrics.objects.filter(pk__in=[older.pk, newer.pk]))
        assert records[0].pk == newer.pk  # newer date → first in default ordering
