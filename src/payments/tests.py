"""
Unit tests for the payments app.

Covers:
  - Payment: model creation, default status, str representation, nullable booking FK
  - Webhook: construct_event compatibility, package activation on payment_intent.succeeded
"""
import hashlib
import hmac
import json
import time
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import RequestFactory
from django.conf import settings

from payments.models import Payment
from payments.views import payments_webhook


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


def _make_webhook_request(payload: dict, secret: str = 'whsec_test_secret') -> object:
    """Build a signed Stripe webhook POST request."""
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    sig_payload = f'{timestamp}.'.encode() + body
    sig = hmac.new(secret.encode(), sig_payload, hashlib.sha256).hexdigest()
    rf = RequestFactory()
    req = rf.post(
        '/payments/webhook/',
        data=body,
        content_type='application/json',
    )
    req.META['HTTP_STRIPE_SIGNATURE'] = f't={timestamp},v1={sig}'
    return req


@pytest.mark.integration
class TestWebhook:
    """Integration tests for the Stripe webhook endpoint.

    Mocks stripe.Webhook.construct_event so no real Stripe calls are made,
    but exercises the full Django view + handler path including DB writes.
    """

    WEBHOOK_SECRET = 'whsec_test_secret'

    def _post(self, event_type: str, intent_data: dict):
        payload = {
            'id': 'evt_test_001',
            'type': event_type,
            'data': {'object': intent_data},
        }
        return _make_webhook_request(payload, self.WEBHOOK_SECRET)

    @patch('payments.views._send_payment_receipt')
    @patch('payments.views._activate_package')
    @patch('stripe.Webhook.construct_event')
    def test_package_purchase_activates_package(
        self, mock_construct, mock_activate, mock_receipt, db, client_profile, package_basic4
    ):
        """payment_intent.succeeded with type=package_purchase must call _activate_package."""
        intent = {
            'id': 'pi_test_pkg',
            'latest_charge': 'ch_test',
            'amount': 16000,
            'description': f'Package: {package_basic4.name}',
            'metadata': {
                'type': 'package_purchase',
                'package_id': str(package_basic4.pk),
                'client_id': str(client_profile.pk),
                'discount_code': '',
                'discount_amount': '0',
                'credit_applied': '0',
                'sibling_discount': '0',
            },
        }
        mock_construct.return_value = {
            'type': 'payment_intent.succeeded',
            'data': {'object': intent},
        }
        Payment.objects.create(
            client=client_profile,
            amount=Decimal('160.00'),
            stripe_payment_intent_id='pi_test_pkg',
            status='pending',
        )

        with self.settings_override():
            req = self._post('payment_intent.succeeded', intent)
            response = payments_webhook(req)

        assert response.status_code == 200
        mock_activate.assert_called_once_with(
            client_id=str(client_profile.pk),
            package_id=str(package_basic4.pk),
            payment_intent_id='pi_test_pkg',
            metadata=intent['metadata'],
            subscription_id='',
        )

    @patch('payments.views._send_payment_receipt')
    @patch('stripe.Webhook.construct_event')
    def test_multi_package_purchase_creates_client_package(
        self, mock_construct, mock_receipt, db, client_profile, player, package_basic4
    ):
        """payment_intent.succeeded with type=multi_package_purchase must create a ClientPackage."""
        from clients.models import ClientPackage

        items = [{'package_id': str(package_basic4.pk), 'player_id': str(player.pk), 'price': '160.00'}]
        intent = {
            'id': 'pi_test_multi',
            'latest_charge': 'ch_test',
            'amount': 16000,
            'description': f'Packages: {package_basic4.name} x1',
            'metadata': {
                'type': 'multi_package_purchase',
                'client_id': str(client_profile.pk),
                'items': json.dumps(items),
                'discount_code': '',
                'discount_amount': '0',
                'credit_applied': '0',
            },
        }
        mock_construct.return_value = {
            'type': 'payment_intent.succeeded',
            'data': {'object': intent},
        }
        Payment.objects.create(
            client=client_profile,
            amount=Decimal('160.00'),
            stripe_payment_intent_id='pi_test_multi',
            status='pending',
        )

        with self.settings_override():
            req = self._post('payment_intent.succeeded', intent)
            response = payments_webhook(req)

        assert response.status_code == 200
        cp = ClientPackage.objects.filter(
            client=client_profile,
            package=package_basic4,
            stripe_payment_id='pi_test_multi',
            status='active',
        ).first()
        assert cp is not None, 'ClientPackage was not created by webhook handler'

    @patch('stripe.Webhook.construct_event')
    def test_bad_signature_returns_400(self, mock_construct, db):
        """A webhook with an invalid signature must be rejected with 400."""
        import stripe as _stripe
        mock_construct.side_effect = _stripe.error.SignatureVerificationError(
            'No signatures found', 't=0,v1=badsig'
        )
        rf = RequestFactory()
        req = rf.post('/payments/webhook/', data=b'bad', content_type='application/json')
        req.META['HTTP_STRIPE_SIGNATURE'] = 't=0,v1=badsig'

        with self.settings_override():
            response = payments_webhook(req)

        assert response.status_code == 400

    @patch('payments.views._send_payment_receipt')
    @patch('stripe.Webhook.construct_event')
    def test_payment_failed_updates_status(self, mock_construct, mock_receipt, db, client_profile):
        """payment_intent.payment_failed must set Payment.status to 'failed'."""
        payment = Payment.objects.create(
            client=client_profile,
            amount=Decimal('160.00'),
            stripe_payment_intent_id='pi_test_fail',
            status='pending',
        )
        mock_construct.return_value = {
            'type': 'payment_intent.payment_failed',
            'data': {'object': {'id': 'pi_test_fail', 'metadata': {}}},
        }

        with self.settings_override():
            req = self._post('payment_intent.payment_failed', {'id': 'pi_test_fail'})
            response = payments_webhook(req)

        assert response.status_code == 200
        payment.refresh_from_db()
        assert payment.status == 'failed'

    @staticmethod
    def settings_override():
        from django.test import override_settings
        return override_settings(
            STRIPE_WEBHOOK_SECRET='whsec_test_secret',
            STRIPE_SECRET_KEY='sk_test_dummy',
        )
