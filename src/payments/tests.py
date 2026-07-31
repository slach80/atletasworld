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

from django.contrib.auth.models import User

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

    @patch('payments.webhook_handlers._send_payment_receipt')
    @patch('payments.webhook_handlers._activate_package')
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

    @patch('payments.webhook_handlers._send_payment_receipt')
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

    @patch('payments.webhook_handlers._send_payment_receipt')
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


# ── Subscription fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def select_package(db):
    from clients.models import Package
    return Package.objects.create(
        name='APC Select Membership',
        package_type='select',
        billing_tier='monthly',
        stripe_price_id='price_test_select',
        price=Decimal('100.00'),
        sessions_included=2,
        validity_weeks=4,
        is_active=True,
        is_purchasable=True,
    )


@pytest.fixture
def select_client(db):
    user = User.objects.create_user(
        username='selectclient', email='select@example.com', password='pass',
        first_name='Select', last_name='Member',
    )
    from clients.models import Client
    return Client.objects.create(
        user=user, client_type='parent',
        stripe_customer_id='cus_test_select',
        select_invited=True,
    )


def _webhook_request(event_type, data, secret='whsec_test_secret'):
    body = json.dumps({'id': 'evt_test', 'type': event_type, 'data': {'object': data}}).encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f'{ts}.'.encode() + body, hashlib.sha256).hexdigest()
    rf = RequestFactory()
    req = rf.post('/payments/webhook/', data=body, content_type='application/json')
    req.META['HTTP_STRIPE_SIGNATURE'] = f't={ts},v1={sig}'
    return req


SETTINGS = dict(STRIPE_WEBHOOK_SECRET='whsec_test_secret', STRIPE_SECRET_KEY='sk_test_dummy')


@pytest.mark.integration
class TestSelectSubscriptionWebhooks:
    """Webhook handlers for Select subscription lifecycle events."""

    # ── invoice.payment_succeeded ──────────────────────────────────────────────

    @patch('payments.views._handle_subscription_renewed')
    @patch('stripe.Webhook.construct_event')
    def test_invoice_payment_succeeded_calls_renewal_handler(
        self, mock_construct, mock_handler, db
    ):
        invoice = {'subscription': 'sub_test_001', 'amount_paid': 10000}
        mock_construct.return_value = {'type': 'invoice.payment_succeeded', 'data': {'object': invoice}}
        from django.test import override_settings
        with override_settings(**SETTINGS):
            resp = payments_webhook(_webhook_request('invoice.payment_succeeded', invoice))
        assert resp.status_code == 200
        mock_handler.assert_called_once_with(invoice)

    @patch('payments.views.NotificationService', create=True)
    @patch('stripe.Webhook.construct_event')
    def test_renewal_extends_expiry_date(self, mock_construct, mock_ns, db, select_client, select_package):
        from clients.models import ClientPackage
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.localdate()
        cp = ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='active', start_date=today,
            expiry_date=today + timedelta(weeks=4),
            sessions_remaining=2,
            stripe_subscription_id='sub_test_renew',
        )
        invoice = {'subscription': 'sub_test_renew', 'amount_paid': 10000}
        mock_construct.return_value = {'type': 'invoice.payment_succeeded', 'data': {'object': invoice}}
        from django.test import override_settings
        with override_settings(**SETTINGS):
            resp = payments_webhook(_webhook_request('invoice.payment_succeeded', invoice))
        assert resp.status_code == 200
        cp.refresh_from_db()
        assert cp.expiry_date == today + timedelta(weeks=4)  # reset to 4 weeks from today
        assert cp.sessions_remaining == 2  # reset to package.sessions_included

    @patch('payments.views.NotificationService', create=True)
    @patch('stripe.Webhook.construct_event')
    def test_renewal_resets_depleted_sessions(self, mock_construct, mock_ns, db, select_client, select_package):
        """Renewal resets sessions_remaining to sessions_included even when depleted."""
        from clients.models import ClientPackage
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.localdate()
        cp = ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='active', start_date=today,
            expiry_date=today + timedelta(weeks=4),
            sessions_remaining=0,  # depleted — would block bookings without reset
            stripe_subscription_id='sub_test_depleted',
        )
        invoice = {'subscription': 'sub_test_depleted', 'amount_paid': 10000}
        mock_construct.return_value = {'type': 'invoice.payment_succeeded', 'data': {'object': invoice}}
        from django.test import override_settings
        with override_settings(**SETTINGS):
            resp = payments_webhook(_webhook_request('invoice.payment_succeeded', invoice))
        assert resp.status_code == 200
        cp.refresh_from_db()
        assert cp.sessions_remaining == select_package.sessions_included  # restored to 2
        assert cp.expiry_date == today + timedelta(weeks=4)

    @patch('payments.views.NotificationService', create=True)
    @patch('payments.webhook_handlers._stripe')
    @patch('stripe.Webhook.construct_event')
    def test_first_invoice_activates_new_package(self, mock_construct, mock_stripe_fn, mock_ns, db, select_client, select_package):
        """invoice.payment_succeeded with billing_reason=subscription_create and no existing CP creates one."""
        from clients.models import ClientPackage
        mock_stripe_obj = MagicMock()
        mock_stripe_fn.return_value = mock_stripe_obj
        mock_stripe_obj.Subscription.retrieve.return_value = {
            'metadata': {
                'client_id': str(select_client.pk),
                'package_id': str(select_package.pk),
            }
        }
        invoice = {
            'subscription': 'sub_test_new_activate',
            'billing_reason': 'subscription_create',
            'amount_paid': 10000,
            'payment_intent': 'pi_test_new_activate',
            'id': 'in_test_new',
        }
        mock_construct.return_value = {'type': 'invoice.payment_succeeded', 'data': {'object': invoice}}
        from django.test import override_settings
        with override_settings(**SETTINGS):
            resp = payments_webhook(_webhook_request('invoice.payment_succeeded', invoice))
        assert resp.status_code == 200
        cp = ClientPackage.objects.filter(
            client=select_client,
            package=select_package,
            stripe_subscription_id='sub_test_new_activate',
            status='active',
        ).first()
        assert cp is not None, 'ClientPackage should be created on first invoice'

    # ── customer.subscription.deleted ─────────────────────────────────────────

    @patch('stripe.Webhook.construct_event')
    def test_cancellation_retains_access_within_paid_period(
        self, mock_construct, db, select_client, select_package
    ):
        from clients.models import ClientPackage
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.localdate()
        cp = ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='active', start_date=today,
            expiry_date=today + timedelta(days=15),
            sessions_remaining=2,
            stripe_subscription_id='sub_test_cancel',
        )
        subscription = {'id': 'sub_test_cancel', 'cancel_at': None, 'canceled_at': int(time.time())}
        mock_construct.return_value = {'type': 'customer.subscription.deleted', 'data': {'object': subscription}}
        from django.test import override_settings
        with override_settings(**SETTINGS):
            resp = payments_webhook(_webhook_request('customer.subscription.deleted', subscription))
        assert resp.status_code == 200
        cp.refresh_from_db()
        assert cp.status == 'active'          # still active — paid through expiry
        assert cp.stripe_subscription_id == '' # subscription ID cleared — no more auto-renewal

    @patch('stripe.Webhook.construct_event')
    def test_cancellation_expires_immediately_if_past_expiry(
        self, mock_construct, db, select_client, select_package
    ):
        from clients.models import ClientPackage
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.localdate()
        cp = ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='active', start_date=today - timedelta(weeks=5),
            expiry_date=today - timedelta(days=1),  # already past
            sessions_remaining=0,
            stripe_subscription_id='sub_test_expired',
        )
        subscription = {'id': 'sub_test_expired', 'cancel_at': None, 'canceled_at': int(time.time())}
        mock_construct.return_value = {'type': 'customer.subscription.deleted', 'data': {'object': subscription}}
        from django.test import override_settings
        with override_settings(**SETTINGS):
            resp = payments_webhook(_webhook_request('customer.subscription.deleted', subscription))
        assert resp.status_code == 200
        cp.refresh_from_db()
        assert cp.status == 'expired'

    # ── invoice.payment_failed ─────────────────────────────────────────────────

    @patch('stripe.Webhook.construct_event')
    def test_payment_failed_creates_notification(
        self, mock_construct, db, select_client, select_package
    ):
        from clients.models import ClientPackage, Notification
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.localdate()
        cp = ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='active', start_date=today,
            expiry_date=today + timedelta(weeks=4),
            sessions_remaining=2,
            stripe_subscription_id='sub_test_failed',
        )
        invoice = {'subscription': 'sub_test_failed', 'attempt_count': 1}
        mock_construct.return_value = {'type': 'invoice.payment_failed', 'data': {'object': invoice}}
        from django.test import override_settings
        with override_settings(**SETTINGS):
            resp = payments_webhook(_webhook_request('invoice.payment_failed', invoice))
        assert resp.status_code == 200
        assert Notification.objects.filter(client=select_client, title__icontains='Payment Failed').exists()

    @patch('stripe.Webhook.construct_event')
    def test_payment_failed_only_notifies_on_first_attempt(
        self, mock_construct, db, select_client, select_package
    ):
        from clients.models import ClientPackage, Notification
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.localdate()
        ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='active', start_date=today,
            expiry_date=today + timedelta(weeks=4),
            sessions_remaining=2,
            stripe_subscription_id='sub_test_retry',
        )
        invoice = {'subscription': 'sub_test_retry', 'attempt_count': 2}  # 2nd attempt
        mock_construct.return_value = {'type': 'invoice.payment_failed', 'data': {'object': invoice}}
        from django.test import override_settings
        with override_settings(**SETTINGS):
            payments_webhook(_webhook_request('invoice.payment_failed', invoice))
        assert not Notification.objects.filter(client=select_client, title__icontains='Payment Failed').exists()

    # ── invoice.upcoming ───────────────────────────────────────────────────────

    @patch('stripe.Webhook.construct_event')
    def test_upcoming_invoice_creates_reminder_notification(
        self, mock_construct, db, select_client, select_package
    ):
        from clients.models import ClientPackage, Notification
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.localdate()
        ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='active', start_date=today,
            expiry_date=today + timedelta(weeks=4),
            sessions_remaining=2,
            stripe_subscription_id='sub_test_upcoming',
        )
        invoice = {
            'subscription': 'sub_test_upcoming',
            'amount_due': 10000,
            'period_end': int(time.time()) + 86400 * 7,
        }
        mock_construct.return_value = {'type': 'invoice.upcoming', 'data': {'object': invoice}}
        from django.test import override_settings
        with override_settings(**SETTINGS):
            resp = payments_webhook(_webhook_request('invoice.upcoming', invoice))
        assert resp.status_code == 200
        assert Notification.objects.filter(client=select_client, title__icontains='Renewing Soon').exists()

    # ── Fall Program event package ─────────────────────────────────────────────

    @patch('payments.views.NotificationService', create=True)
    @patch('stripe.Webhook.construct_event')
    def test_renewal_uses_event_end_date_for_expiry(
        self, mock_construct, mock_ns, db, select_client
    ):
        """Renewal of a Fall Program package pins expiry to event_end_date, not today+N weeks."""
        import datetime
        from clients.models import Package, ClientPackage
        from django.utils import timezone
        today = timezone.localdate()
        fall_pkg = Package.objects.create(
            name='Elite 24 Fall — Monthly',
            package_type='elite24',
            billing_tier='monthly',
            stripe_price_id='price_test_fall_monthly',
            price=Decimal('160.00'),
            sessions_included=24,
            validity_weeks=12,
            is_active=True,
            is_purchasable=True,
            event_start_date=datetime.date(2026, 8, 17),
            event_end_date=datetime.date(2026, 11, 8),
            program_group='Elite 24 Fall',
        )
        cp = ClientPackage.objects.create(
            client=select_client, package=fall_pkg,
            status='active', start_date=today,
            expiry_date=today + datetime.timedelta(weeks=4),
            sessions_remaining=24,
            stripe_subscription_id='sub_test_fall_renew',
        )
        invoice = {'subscription': 'sub_test_fall_renew', 'amount_paid': 16000}
        mock_construct.return_value = {'type': 'invoice.payment_succeeded', 'data': {'object': invoice}}
        from django.test import override_settings
        with override_settings(**SETTINGS):
            resp = payments_webhook(_webhook_request('invoice.payment_succeeded', invoice))
        assert resp.status_code == 200
        cp.refresh_from_db()
        assert cp.expiry_date == datetime.date(2026, 11, 8)   # pinned to event_end_date
        assert cp.sessions_remaining == 24                    # reset to sessions_included

    @patch('payments.views._get_or_create_stripe_customer', return_value='cus_test_fall')
    @patch('payments.views._stripe')
    @patch('stripe.Webhook.construct_event')
    def test_fall_subscription_sets_cancel_at(
        self, mock_construct, mock_stripe_fn, mock_get_customer, db, select_client
    ):
        """create_package_subscription passes cancel_at when package has event_end_date."""
        import datetime
        from clients.models import Package
        from django.test import RequestFactory
        from django.test import override_settings
        from payments.views import create_package_subscription

        fall_pkg = Package.objects.create(
            name='Elite 24 Fall — Monthly',
            package_type='elite24',
            billing_tier='monthly',
            stripe_price_id='price_test_fall',
            price=Decimal('160.00'),
            sessions_included=24,
            validity_weeks=12,
            is_active=True,
            is_purchasable=True,
            event_start_date=datetime.date(2026, 8, 17),
            event_end_date=datetime.date(2026, 11, 8),
            program_group='Elite 24 Fall',
        )

        mock_s = MagicMock()
        mock_stripe_fn.return_value = mock_s
        mock_s.PaymentMethod.attach.return_value = MagicMock()
        mock_s.Customer.modify.return_value = MagicMock()
        mock_sub = MagicMock()
        mock_sub.id = 'sub_test_fall'
        mock_sub.status = 'active'
        mock_sub.latest_invoice = MagicMock(payment_intent=MagicMock(client_secret='pi_secret'))
        mock_s.Subscription.create.return_value = mock_sub
        mock_s.Subscription.modify.return_value = mock_sub

        rf = RequestFactory()
        req = rf.post(f'/portal/packages/{fall_pkg.pk}/subscribe/', {'payment_method_id': 'pm_test'})
        req.user = select_client.user

        import datetime as _dt
        expected_cancel_at = int(_dt.datetime.combine(datetime.date(2026, 11, 8), _dt.time(23, 59, 59)).timestamp())

        with override_settings(**SETTINGS):
            resp = create_package_subscription(req, fall_pkg.pk)

        assert resp.status_code == 200
        call_kwargs = mock_s.Subscription.create.call_args[1]
        assert 'cancel_at' in call_kwargs
        assert call_kwargs['cancel_at'] == expected_cancel_at


@pytest.mark.integration
class TestSelectSubscriptionBillingLogic:
    """Tests for trial_end calculation in create_package_subscription."""

    @staticmethod
    def _make_stripe_mock(status='active', client_secret=None):
        sub = MagicMock()
        sub.id = 'sub_mock_001'
        sub.status = status
        sub.latest_invoice.payment_intent.client_secret = client_secret
        return sub

    @patch('payments.views._get_or_create_stripe_customer', return_value='cus_test')
    @patch('payments.views._stripe')
    def test_new_member_no_legacy_package_charges_immediately(
        self, mock_stripe_fn, mock_customer, db, select_client, select_package
    ):
        """No prior package → no trial → charges immediately."""
        from django.test import Client as TestClient, override_settings
        mock_s = MagicMock()
        mock_s.PaymentMethod.attach.return_value = None
        mock_s.Customer.modify.return_value = None
        mock_s.Subscription.create.return_value = self._make_stripe_mock(status='active', client_secret='cs_test')
        mock_s.Subscription.modify.return_value = None
        mock_stripe_fn.return_value = mock_s

        tc = TestClient()
        tc.force_login(select_client.user)
        with override_settings(STRIPE_SECRET_KEY='sk_test_dummy'):
            resp = tc.post(
                f'/portal/packages/{select_package.pk}/subscribe/',
                {'payment_method_id': 'pm_test_001'},
            )
        assert resp.status_code == 200
        call_kwargs = mock_s.Subscription.create.call_args[1]
        assert 'trial_end' not in call_kwargs  # no trial for new member

    @patch('payments.views._get_or_create_stripe_customer', return_value='cus_test')
    @patch('payments.views._stripe')
    def test_legacy_member_future_anniversary_gets_trial(
        self, mock_stripe_fn, mock_customer, db, select_client, select_package
    ):
        """Legacy member whose 1-month anniversary is in the future → trial until then."""
        from clients.models import ClientPackage
        from django.test import Client as TestClient, override_settings
        from django.utils import timezone
        from datetime import timedelta

        today = timezone.localdate()
        # Started 2 weeks ago → anniversary in 2 more weeks
        ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='expired', start_date=today - timedelta(weeks=2),
            expiry_date=today + timedelta(weeks=22),
            sessions_remaining=0,
            stripe_subscription_id='',
            stripe_payment_id='pi_legacy_test',
        )
        mock_s = MagicMock()
        mock_s.PaymentMethod.attach.return_value = None
        mock_s.Customer.modify.return_value = None
        mock_s.Subscription.create.return_value = self._make_stripe_mock(status='trialing')
        mock_s.Subscription.modify.return_value = None
        mock_stripe_fn.return_value = mock_s

        tc = TestClient()
        tc.force_login(select_client.user)
        with override_settings(STRIPE_SECRET_KEY='sk_test_dummy'):
            resp = tc.post(
                f'/portal/packages/{select_package.pk}/subscribe/',
                {'payment_method_id': 'pm_test_002'},
            )
        assert resp.status_code == 200
        call_kwargs = mock_s.Subscription.create.call_args[1]
        assert 'trial_end' in call_kwargs  # trial applied

    @patch('payments.views._get_or_create_stripe_customer', return_value='cus_test')
    @patch('payments.views._stripe')
    def test_legacy_member_past_anniversary_charges_immediately(
        self, mock_stripe_fn, mock_customer, db, select_client, select_package
    ):
        """Legacy member whose 1-month anniversary has passed → no trial."""
        from clients.models import ClientPackage
        from django.test import Client as TestClient, override_settings
        from django.utils import timezone
        from datetime import timedelta

        today = timezone.localdate()
        # Started 6 weeks ago → anniversary already passed
        ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='expired', start_date=today - timedelta(weeks=6),
            expiry_date=today + timedelta(weeks=18),
            sessions_remaining=0,
            stripe_subscription_id='',
            stripe_payment_id='pi_legacy_past',
        )
        mock_s = MagicMock()
        mock_s.PaymentMethod.attach.return_value = None
        mock_s.Customer.modify.return_value = None
        mock_s.Subscription.create.return_value = self._make_stripe_mock(status='active', client_secret='cs_test')
        mock_s.Subscription.modify.return_value = None
        mock_stripe_fn.return_value = mock_s

        tc = TestClient()
        tc.force_login(select_client.user)
        with override_settings(STRIPE_SECRET_KEY='sk_test_dummy'):
            resp = tc.post(
                f'/portal/packages/{select_package.pk}/subscribe/',
                {'payment_method_id': 'pm_test_003'},
            )
        assert resp.status_code == 200
        call_kwargs = mock_s.Subscription.create.call_args[1]
        assert 'trial_end' not in call_kwargs  # no trial

    @patch('payments.views._get_or_create_stripe_customer', return_value='cus_test')
    @patch('payments.views._stripe')
    def test_sibling_subscription_applies_50_percent_coupon(
        self, mock_stripe_fn, mock_customer, db, select_client, select_package
    ):
        """Client already has an active sub for same package → SIBLING50 coupon applied."""
        from clients.models import ClientPackage
        from django.test import Client as TestClient, override_settings
        from django.utils import timezone
        from datetime import timedelta

        today = timezone.localdate()
        # Existing active subscription for first player
        ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='active', start_date=today,
            expiry_date=today + timedelta(weeks=4),
            sessions_remaining=0,
            stripe_subscription_id='sub_existing_sibling',
            stripe_payment_id='sub_existing_sibling',
        )
        mock_s = MagicMock()
        mock_s.PaymentMethod.attach.return_value = None
        mock_s.Customer.modify.return_value = None
        mock_s.Subscription.create.return_value = self._make_stripe_mock(status='active', client_secret='cs_test')
        mock_s.Subscription.modify.return_value = None
        mock_stripe_fn.return_value = mock_s

        tc = TestClient()
        tc.force_login(select_client.user)
        with override_settings(STRIPE_SECRET_KEY='sk_test_dummy'):
            resp = tc.post(
                f'/portal/packages/{select_package.pk}/subscribe/',
                {'payment_method_id': 'pm_test_sibling'},
            )
        assert resp.status_code == 200
        call_kwargs = mock_s.Subscription.create.call_args[1]
        assert call_kwargs.get('discounts') == [{'coupon': 'SIBLING50'}]
        assert call_kwargs['metadata']['sibling_discount'] == 'true'

    @patch('payments.views._get_or_create_stripe_customer', return_value='cus_test')
    @patch('payments.views._stripe')
    def test_no_sibling_subscription_no_coupon(
        self, mock_stripe_fn, mock_customer, db, select_client, select_package
    ):
        """No existing active sub → no SIBLING50 coupon applied."""
        from django.test import Client as TestClient, override_settings

        mock_s = MagicMock()
        mock_s.PaymentMethod.attach.return_value = None
        mock_s.Customer.modify.return_value = None
        mock_s.Subscription.create.return_value = self._make_stripe_mock(status='active', client_secret='cs_test')
        mock_s.Subscription.modify.return_value = None
        mock_stripe_fn.return_value = mock_s

        tc = TestClient()
        tc.force_login(select_client.user)
        with override_settings(STRIPE_SECRET_KEY='sk_test_dummy'):
            resp = tc.post(
                f'/portal/packages/{select_package.pk}/subscribe/',
                {'payment_method_id': 'pm_test_no_sibling'},
            )
        assert resp.status_code == 200
        call_kwargs = mock_s.Subscription.create.call_args[1]
        assert 'discounts' not in call_kwargs
        assert call_kwargs['metadata']['sibling_discount'] == 'false'


@pytest.mark.integration
class TestSelectSubscriptionUI:
    """Tests for subscription-related UI gating."""

    @staticmethod
    def _add_player(client):
        from clients.models import Player
        return Player.objects.create(
            client=client, first_name='Test', last_name='Player',
            birth_year=2012, is_active=True,
        )

    def test_uninvited_client_cannot_see_select_section(self, db, select_client, select_package):
        from django.test import Client as TestClient
        self._add_player(select_client)
        select_client.select_invited = False
        select_client.save()
        tc = TestClient()
        tc.force_login(select_client.user)
        resp = tc.get('/portal/packages/')
        assert resp.status_code == 200
        assert b'Join APC Select' not in resp.content

    def test_invited_client_sees_select_section(self, db, select_client, select_package):
        from django.test import Client as TestClient
        self._add_player(select_client)
        tc = TestClient()
        tc.force_login(select_client.user)
        resp = tc.get('/portal/packages/')
        assert resp.status_code == 200
        assert b'Join APC Select' in resp.content

    def test_active_member_sees_already_a_member(self, db, select_client, select_package):
        from django.test import Client as TestClient
        from clients.models import ClientPackage
        from django.utils import timezone
        from datetime import timedelta
        self._add_player(select_client)
        today = timezone.localdate()
        ClientPackage.objects.create(
            client=select_client, package=select_package,
            status='active', start_date=today,
            expiry_date=today + timedelta(weeks=4),
            sessions_remaining=2,
        )
        tc = TestClient()
        tc.force_login(select_client.user)
        resp = tc.get('/portal/packages/')
        assert resp.status_code == 200
        assert b'Already a Member' in resp.content
