"""
Unit tests for referral program functionality.

Tests cover:
- Referral code generation on user creation
- Code uniqueness enforcement
- Middleware URL parameter capture
- Signal-driven referral tracking
- Self-referral prevention
- Activation on first purchase (client & coach)
- Expiry window enforcement
- Duplicate activation prevention
- On-demand code generation for existing users
"""
import pytest
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth.models import User, Group
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from clients.models import (
    Client, ReferralCode, Referral, ReferralPayout, ClientCredit, ClientPackage, Package
)
from clients.middleware import ReferralCodeMiddleware
from clients.services import ReferralService
from coaches.models import Coach
from payments.models import Payment


class ReferralCodeGenerationTests(TestCase):
    """Test automatic referral code generation."""

    def test_referral_code_generated_on_user_creation(self):
        """Verify that a referral code is auto-generated when a user is created."""
        user = User.objects.create_user(username='testuser', email='test@example.com', password='pass')

        # Check that a referral code was created
        self.assertTrue(ReferralCode.objects.filter(user=user).exists())
        code = ReferralCode.objects.get(user=user)
        self.assertEqual(len(code.code), 8)
        self.assertTrue(code.code.isupper())

    def test_referral_code_uniqueness(self):
        """Verify that generated referral codes are unique."""
        user1 = User.objects.create_user(username='user1', email='user1@example.com', password='pass')
        user2 = User.objects.create_user(username='user2', email='user2@example.com', password='pass')

        code1 = ReferralCode.objects.get(user=user1)
        code2 = ReferralCode.objects.get(user=user2)

        self.assertNotEqual(code1.code, code2.code)


class ReferralMiddlewareTests(TestCase):
    """Test referral code capture middleware."""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ReferralCodeMiddleware(get_response=lambda r: None)

    def test_middleware_captures_ref_param(self):
        """Verify middleware captures ?ref=CODE from URL and stores in session."""
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get('/?ref=TESTCODE123')
        request.user = AnonymousUser()
        request.session = {}

        self.middleware(request)

        self.assertEqual(request.session.get('referral_code'), 'TESTCODE123')

    def test_middleware_ignores_authenticated_users(self):
        """Verify middleware does not capture referral codes for authenticated users."""
        request = self.factory.get('/?ref=TESTCODE123')
        request.user = User.objects.create_user(username='existing', password='pass')
        request.session = {}

        self.middleware(request)

        self.assertNotIn('referral_code', request.session)


class ReferralTrackingTests(TestCase):
    """Test referral tracking signal handlers."""

    def setUp(self):
        # Create client group
        self.client_group, _ = Group.objects.get_or_create(name='Client')
        self.coach_group, _ = Group.objects.get_or_create(name='Coach')

    def test_referral_tracked_on_signup(self):
        """Verify referral relationship is created when user signs up with code."""
        # Create referrer
        referrer = User.objects.create_user(username='referrer', email='referrer@example.com', password='pass')
        referrer.groups.add(self.client_group)
        referrer_code = ReferralCode.objects.get(user=referrer)

        # Simulate signup with referral code
        from allauth.account.signals import user_signed_up
        from django.test import RequestFactory

        request = RequestFactory().post('/signup')
        request.session = {'referral_code': referrer_code.code}
        request.POST = {}

        referred_user = User.objects.create_user(username='referred', email='referred@example.com', password='pass')
        referred_user.groups.add(self.client_group)

        # Manually trigger the signal (in real flow, this happens automatically)
        user_signed_up.send(sender=User, request=request, user=referred_user)

        # Verify referral was created
        self.assertTrue(Referral.objects.filter(
            referrer_user=referrer,
            referred_user=referred_user,
            status='pending'
        ).exists())

    def test_self_referral_prevented(self):
        """Verify users cannot refer themselves."""
        user = User.objects.create_user(username='user', email='user@example.com', password='pass')
        user.groups.add(self.client_group)
        user_code = ReferralCode.objects.get(user=user)

        # Try to self-refer
        from allauth.account.signals import user_signed_up
        from django.test import RequestFactory

        request = RequestFactory().post('/signup')
        request.session = {'referral_code': user_code.code}
        request.POST = {}

        # Trigger signal
        user_signed_up.send(sender=User, request=request, user=user)

        # Verify no referral was created
        self.assertFalse(Referral.objects.filter(referred_user=user).exists())


class ReferralActivationTests(TestCase):
    """Test referral activation on first purchase."""

    def setUp(self):
        self.client_group, _ = Group.objects.get_or_create(name='Client')
        self.coach_group, _ = Group.objects.get_or_create(name='Coach')

    @patch('clients.services.run_task')
    def test_activation_on_first_purchase_client(self, mock_run_task):
        """Verify client referrer receives 10% credit on referred user's first purchase."""
        # Create referrer (client)
        referrer = User.objects.create_user(username='referrer', email='referrer@example.com', password='pass')
        referrer.groups.add(self.client_group)
        referrer_client = Client.objects.create(user=referrer)
        referrer_code = ReferralCode.objects.get(user=referrer)

        # Create referred user
        referred = User.objects.create_user(username='referred', email='referred@example.com', password='pass')
        referred.groups.add(self.client_group)
        referred_client = Client.objects.create(user=referred)

        # Create referral
        referral = Referral.objects.create(
            referrer_user=referrer,
            referred_user=referred,
            referral_code=referrer_code.code,
            referrer_type='client',
            status='pending',
            referral_window_expires=timezone.now() + timedelta(days=60)
        )

        # Simulate first purchase
        purchase_amount = Decimal('100.00')
        ReferralService.check_and_activate(referred_client, purchase_amount)

        # Verify referral activated
        referral.refresh_from_db()
        self.assertEqual(referral.status, 'activated')
        self.assertEqual(referral.reward_amount, Decimal('10.00'))  # 10% of 100

        # Verify async task was dispatched
        mock_run_task.assert_called_once()

    @patch('clients.services.run_task')
    def test_activation_on_first_purchase_coach(self, mock_run_task):
        """Verify coach referrer receives 20% payout request on referred user's first purchase."""
        # Create referrer (coach)
        referrer = User.objects.create_user(username='coach', email='coach@example.com', password='pass')
        referrer.groups.add(self.coach_group)
        Coach.objects.create(user=referrer)
        referrer_code = ReferralCode.objects.get(user=referrer)

        # Create referred user
        referred = User.objects.create_user(username='referred', email='referred@example.com', password='pass')
        referred.groups.add(self.client_group)
        referred_client = Client.objects.create(user=referred)

        # Create referral
        referral = Referral.objects.create(
            referrer_user=referrer,
            referred_user=referred,
            referral_code=referrer_code.code,
            referrer_type='coach',
            status='pending',
            referral_window_expires=timezone.now() + timedelta(days=60)
        )

        # Simulate first purchase
        purchase_amount = Decimal('100.00')
        ReferralService.check_and_activate(referred_client, purchase_amount)

        # Verify referral activated
        referral.refresh_from_db()
        self.assertEqual(referral.status, 'activated')
        self.assertEqual(referral.reward_amount, Decimal('20.00'))  # 20% of 100

        # Verify async task was dispatched
        mock_run_task.assert_called_once()

    def test_activation_skipped_if_window_expired(self):
        """Verify activation is skipped if referral window has expired."""
        # Create referrer
        referrer = User.objects.create_user(username='referrer', email='referrer@example.com', password='pass')
        referrer.groups.add(self.client_group)
        Client.objects.create(user=referrer)
        referrer_code = ReferralCode.objects.get(user=referrer)

        # Create referred user
        referred = User.objects.create_user(username='referred', email='referred@example.com', password='pass')
        referred.groups.add(self.client_group)
        referred_client = Client.objects.create(user=referred)

        # Create referral with expired window
        referral = Referral.objects.create(
            referrer_user=referrer,
            referred_user=referred,
            referral_code=referrer_code.code,
            referrer_type='client',
            status='pending',
            referral_window_expires=timezone.now() - timedelta(days=1)  # Expired
        )

        # Attempt activation
        purchase_amount = Decimal('100.00')
        result = ReferralService.check_and_activate(referred_client, purchase_amount)

        # Verify activation did not happen
        self.assertIsNone(result)
        referral.refresh_from_db()
        self.assertEqual(referral.status, 'pending')

    @patch('clients.services.run_task')
    def test_duplicate_activation_prevented(self, mock_run_task):
        """Verify referral cannot be activated twice."""
        # Create referrer
        referrer = User.objects.create_user(username='referrer', email='referrer@example.com', password='pass')
        referrer.groups.add(self.client_group)
        Client.objects.create(user=referrer)
        referrer_code = ReferralCode.objects.get(user=referrer)

        # Create referred user
        referred = User.objects.create_user(username='referred', email='referred@example.com', password='pass')
        referred.groups.add(self.client_group)
        referred_client = Client.objects.create(user=referred)

        # Create referral
        referral = Referral.objects.create(
            referrer_user=referrer,
            referred_user=referred,
            referral_code=referrer_code.code,
            referrer_type='client',
            status='pending',
            referral_window_expires=timezone.now() + timedelta(days=60)
        )

        # First activation
        purchase_amount = Decimal('100.00')
        ReferralService.check_and_activate(referred_client, purchase_amount)

        # Attempt second activation
        second_result = ReferralService.check_and_activate(referred_client, Decimal('50.00'))

        # Verify second activation was skipped
        self.assertIsNone(second_result)
        referral.refresh_from_db()
        self.assertEqual(referral.status, 'activated')
        self.assertEqual(referral.reward_amount, Decimal('10.00'))  # Still original amount

        # Verify task only dispatched once
        self.assertEqual(mock_run_task.call_count, 1)


class OnDemandCodeGenerationTests(TestCase):
    """Test on-demand code generation for existing users."""

    def test_existing_user_code_generated_on_demand(self):
        """Verify code is generated on-demand for users created before referral system."""
        # Create user without triggering signal (simulate old user)
        user = User.objects.create(username='olduser', email='old@example.com')
        user.set_password('pass')
        user.save()

        # Manually delete the auto-generated code to simulate pre-referral user
        ReferralCode.objects.filter(user=user).delete()

        # Verify no code exists
        self.assertFalse(ReferralCode.objects.filter(user=user).exists())

        # Request code (simulates first visit to referral page)
        code = ReferralService.get_or_create_code(user)

        # Verify code was created
        self.assertIsNotNone(code)
        self.assertEqual(code.user, user)
        self.assertEqual(len(code.code), 8)
