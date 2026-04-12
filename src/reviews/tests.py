"""
Unit tests for the reviews app.

Covers:
  - Review: model creation, str representation, default flags, nullable booking FK
"""
import pytest

from reviews.models import Review


@pytest.mark.unit
class TestReviewModel:
    """Tests for the Review model (client ratings of coaches)."""

    def test_str_representation(self, review):
        """__str__ should identify the client, rating, and coach."""
        result = str(review)
        assert 'stars' in result.lower() or '5' in result

    def test_rating_1_through_5_are_valid(self, db, client_profile, coach, pending_booking):
        """All integer ratings from 1 to 5 should be accepted without error."""
        for rating in range(1, 6):
            r = Review.objects.create(
                client=client_profile,
                coach=coach,
                rating=rating,
                comment=f'{rating}-star comment',
            )
            assert r.rating == rating
            r.delete()  # clean up between iterations

    def test_default_is_approved_true(self, db, client_profile, coach):
        """Reviews should be approved by default to avoid hiding feedback until manually checked."""
        r = Review.objects.create(
            client=client_profile,
            coach=coach,
            rating=4,
        )
        assert r.is_approved is True

    def test_default_is_featured_false(self, db, client_profile, coach):
        """Reviews should not be featured by default — owner must explicitly promote them."""
        r = Review.objects.create(
            client=client_profile,
            coach=coach,
            rating=5,
        )
        assert r.is_featured is False

    def test_ordering_by_created_at_descending(self, db, client_profile, coach):
        """Reviews should be ordered newest first (default Meta ordering)."""
        r1 = Review.objects.create(client=client_profile, coach=coach, rating=3)
        r2 = Review.objects.create(client=client_profile, coach=coach, rating=5)
        reviews = list(Review.objects.filter(pk__in=[r1.pk, r2.pk]))
        assert reviews[0].pk == r2.pk  # r2 created later → appears first

    def test_review_without_booking_is_allowed(self, db, client_profile, coach):
        """Reviews may be created without a linked booking (e.g. imported reviews)."""
        r = Review.objects.create(
            client=client_profile,
            coach=coach,
            rating=5,
            booking=None,
        )
        assert r.booking is None
        assert r.pk is not None
