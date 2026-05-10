"""
Test retroactive referral code entry.
"""
import pytest
from unittest.mock import patch
from django.test import TestCase, Client as TestClient
from django.contrib.auth.models import User, Group
from django.utils import timezone
from datetime import timedelta

from clients.models import Client, ReferralCode, Referral


class RetroactiveReferralTests(TestCase):
    """Test adding referral code after signup."""

    def setUp(self):
        self.client_group, _ = Group.objects.get_or_create(name='Client')
        self.test_client = TestClient()

    def test_user_can_add_referral_code_retroactively(self):
        """Verify user who signed up without code can add one later."""
        # Create referrer
        referrer = User.objects.create_user(username='referrer', email='referrer@example.com', password='pass')
        referrer.groups.add(self.client_group)
        Client.objects.create(user=referrer)
        referrer_code = ReferralCode.objects.get(user=referrer)

        # Create user without referral
        user = User.objects.create_user(username='newuser', email='new@example.com', password='pass')
        user.groups.add(self.client_group)
        Client.objects.create(user=user)

        # Verify no referral exists
        self.assertFalse(Referral.objects.filter(referred_user=user).exists())

        # Log in and add code
        self.test_client.login(username='newuser', password='pass')
        response = self.test_client.post('/portal/referral/add-code/', {
            'referral_code': referrer_code.code
        })

        # Verify referral created
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Referral.objects.filter(
            referrer_user=referrer,
            referred_user=user,
            status='pending'
        ).exists())

    def test_cannot_add_duplicate_referral(self):
        """Verify user cannot add referral code if already referred."""
        # Create referrer
        referrer = User.objects.create_user(username='referrer', email='referrer@example.com', password='pass')
        referrer.groups.add(self.client_group)
        Client.objects.create(user=referrer)
        referrer_code = ReferralCode.objects.get(user=referrer)

        # Create user with existing referral
        user = User.objects.create_user(username='newuser', email='new@example.com', password='pass')
        user.groups.add(self.client_group)
        Client.objects.create(user=user)

        Referral.objects.create(
            referrer_user=referrer,
            referred_user=user,
            referral_code=referrer_code.code,
            referrer_type='client',
            status='pending',
            referral_window_expires=timezone.now() + timedelta(days=60)
        )

        # Try to add another code
        self.test_client.login(username='newuser', password='pass')
        response = self.test_client.post('/portal/referral/add-code/', {
            'referral_code': referrer_code.code
        })

        # Should show error message
        self.assertEqual(response.status_code, 302)
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('already have a referral' in str(m) for m in messages))

    def test_cannot_use_own_referral_code(self):
        """Verify user cannot refer themselves."""
        user = User.objects.create_user(username='user', email='user@example.com', password='pass')
        user.groups.add(self.client_group)
        Client.objects.create(user=user)
        user_code = ReferralCode.objects.get(user=user)

        # Try to use own code
        self.test_client.login(username='user', password='pass')
        response = self.test_client.post('/portal/referral/add-code/', {
            'referral_code': user_code.code
        })

        # Should show error
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('cannot use your own' in str(m) for m in messages))
        self.assertFalse(Referral.objects.filter(referred_user=user).exists())

    def test_invalid_code_shows_error(self):
        """Verify invalid referral code shows appropriate error."""
        user = User.objects.create_user(username='user', email='user@example.com', password='pass')
        user.groups.add(self.client_group)
        Client.objects.create(user=user)

        self.test_client.login(username='user', password='pass')
        response = self.test_client.post('/portal/referral/add-code/', {
            'referral_code': 'INVALID123'
        })

        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Invalid referral code' in str(m) for m in messages))
        self.assertFalse(Referral.objects.filter(referred_user=user).exists())

    def test_referral_page_shows_form_if_not_referred(self):
        """Verify 'Add Code' form appears on referral page if user wasn't referred."""
        user = User.objects.create_user(username='user', email='user@example.com', password='pass')
        user.groups.add(self.client_group)
        Client.objects.create(user=user)

        self.test_client.login(username='user', password='pass')
        response = self.test_client.get('/portal/referral/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Were You Referred?')
        self.assertContains(response, 'Apply Code')

    def test_referral_page_hides_form_if_already_referred(self):
        """Verify 'Add Code' form hidden if user already has referral."""
        # Create referrer
        referrer = User.objects.create_user(username='referrer', email='referrer@example.com', password='pass')
        referrer.groups.add(self.client_group)
        Client.objects.create(user=referrer)
        referrer_code = ReferralCode.objects.get(user=referrer)

        # Create referred user
        user = User.objects.create_user(username='user', email='user@example.com', password='pass')
        user.groups.add(self.client_group)
        Client.objects.create(user=user)

        Referral.objects.create(
            referrer_user=referrer,
            referred_user=user,
            referral_code=referrer_code.code,
            referrer_type='client',
            status='pending',
            referral_window_expires=timezone.now() + timedelta(days=60)
        )

        self.test_client.login(username='user', password='pass')
        response = self.test_client.get('/portal/referral/')

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Were You Referred?')
