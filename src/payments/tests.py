"""
Unit tests for the payments app.

Covers:
  - Payment: model creation, default status, str representation, nullable booking FK
"""
import pytest
from decimal import Decimal

from payments.models import Payment


@pytest.mark.unit
class TestPaymentModel:
    """Tests for the Payment model (Stripe payment records)."""

    def test_str_representation(self, db, client_profile):
        """__str__ should include amount, client name, and status."""
        payment = Payment.objects.create(
            client=client_profile,
            amount=Decimal('40.00'),
            stripe_payment_intent_id='pi_test_001',
            status='succeeded',
        )
        result = str(payment)
        assert '40' in result
        assert 'succeeded' in result

    def test_default_status_is_pending(self, db, client_profile):
        """Newly created payments should have 'pending' status before Stripe confirms them."""
        payment = Payment.objects.create(
            client=client_profile,
            amount=Decimal('200.00'),
            stripe_payment_intent_id='pi_test_002',
        )
        assert payment.status == 'pending'

    def test_all_status_choices_are_valid(self, db, client_profile):
        """All defined status choices should be saveable without error."""
        valid_statuses = ['pending', 'succeeded', 'failed', 'refunded']
        for i, status in enumerate(valid_statuses):
            payment = Payment.objects.create(
                client=client_profile,
                amount=Decimal('10.00'),
                stripe_payment_intent_id=f'pi_test_status_{i}',
                status=status,
            )
            assert payment.status == status

    def test_ordering_by_created_at_descending(self, db, client_profile):
        """Payments should be ordered newest first (default Meta ordering)."""
        p1 = Payment.objects.create(
            client=client_profile,
            amount=Decimal('10.00'),
            stripe_payment_intent_id='pi_order_1',
        )
        p2 = Payment.objects.create(
            client=client_profile,
            amount=Decimal('20.00'),
            stripe_payment_intent_id='pi_order_2',
        )
        payments = list(Payment.objects.filter(
            stripe_payment_intent_id__in=['pi_order_1', 'pi_order_2']
        ))
        # Most recently created (p2) should come first
        assert payments[0].pk == p2.pk

    def test_payment_without_booking_is_allowed(self, db, client_profile):
        """The booking FK is nullable — standalone payments (e.g. package purchases) are valid."""
        payment = Payment.objects.create(
            client=client_profile,
            amount=Decimal('200.00'),
            stripe_payment_intent_id='pi_no_booking',
            booking=None,
        )
        assert payment.booking is None
        assert payment.pk is not None
