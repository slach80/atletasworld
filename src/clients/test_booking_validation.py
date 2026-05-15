"""
Tests for create_booking_direct endpoint validation logic.

Covers: free sessions, package deduction (player-specific + family fallback),
linked_packages check, drop-in-only session types, exhausted packages,
mixed-cart scenarios, over-booking, multi-player families, block availability,
and waiver requirements.
"""
import json
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import Client as TestClient, TestCase
from django.utils import timezone

from bookings.models import Booking, SessionType
from clients.models import (
    Client,
    ClientPackage,
    ClientWaiver,
    Package,
    Player,
)
from coaches.models import Coach, ScheduleBlock


class BookingValidationTestCase(TestCase):
    """Base class with shared test setup for create_booking_direct tests."""

    URL = '/portal/book/create-direct/'

    def setUp(self):
        # Groups
        self.client_group, _ = Group.objects.get_or_create(name='Client')

        # ── Client user ───────────────────────────────────────────────────
        self.user = User.objects.create_user(
            username='parent1',
            email='parent1@example.com',
            password='testpass123',
            first_name='Sarah',
            last_name='Johnson',
        )
        self.user.groups.add(self.client_group)
        self.client_profile = Client.objects.create(
            user=self.user,
            client_type='parent',
            phone='555-1000',
        )

        # Waiver (valid for current year)
        ClientWaiver.objects.create(
            client=self.client_profile,
            full_name='Sarah Johnson',
            signature_text='Sarah Johnson',
            waiver_version=ClientWaiver.WAIVER_VERSION,
            valid_year=timezone.now().year,
        )

        # ── Players ──────────────────────────────────────────────────────
        self.player_noah = Player.objects.create(
            client=self.client_profile,
            first_name='Noah',
            last_name='Johnson',
            birth_year=2014,
            gender='M',
            skill_level='intermediate',
            is_active=True,
        )
        self.player_ethan = Player.objects.create(
            client=self.client_profile,
            first_name='Ethan',
            last_name='Johnson',
            birth_year=2012,
            gender='M',
            skill_level='beginner',
            is_active=True,
        )

        # ── Coach ────────────────────────────────────────────────────────
        self.coach_user = User.objects.create_user(
            username='coach1',
            email='coach1@example.com',
            password='testpass123',
            first_name='Mirko',
            last_name='Coach',
        )
        self.coach = Coach.objects.create(
            user=self.coach_user,
            slug='mirko-coach',
            bio='Test coach',
            hourly_rate=Decimal('75.00'),
            is_active=True,
            profile_enabled=True,
        )

        # ── Session types ────────────────────────────────────────────────
        self.session_type_group = SessionType.objects.create(
            name='Group Training',
            session_format='group',
            duration_minutes=60,
            price=Decimal('40.00'),
            drop_in_price=Decimal('50.00'),
            max_participants=10,
            allow_package=True,
            is_active=True,
        )
        self.session_type_dropin = SessionType.objects.create(
            name='Pick-Up Game',
            session_format='pickup',
            duration_minutes=90,
            price=Decimal('25.00'),
            drop_in_price=Decimal('25.00'),
            max_participants=20,
            allow_package=False,  # never uses packages
            is_active=True,
        )
        self.session_type_linked = SessionType.objects.create(
            name='Elite Training',
            session_format='group',
            duration_minutes=60,
            price=Decimal('60.00'),
            drop_in_price=Decimal('75.00'),
            max_participants=8,
            allow_package=True,
            is_active=True,
        )

        # ── Packages (catalog) ───────────────────────────────────────────
        self.package_basic = Package.objects.create(
            name='Basic 4',
            package_type='basic4',
            price=Decimal('200.00'),
            sessions_included=4,
            validity_weeks=4,
            is_active=True,
        )
        self.package_elite = Package.objects.create(
            name='Elite 24',
            package_type='elite24',
            price=Decimal('600.00'),
            sessions_included=24,
            validity_weeks=12,
            is_active=True,
        )

        # Link the Elite session type to only the elite package
        self.session_type_linked.linked_packages.add(self.package_elite)

        # ── Test HTTP client ─────────────────────────────────────────────
        self.http_client = TestClient()
        self.http_client.login(username='parent1', password='testpass123')

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _create_block(self, session_type=None, price_override=None,
                      max_participants=10, current_participants=0,
                      status='available', days_ahead=3):
        """Create a schedule block and attach a session type."""
        if session_type is None:
            session_type = self.session_type_group
        block = ScheduleBlock.objects.create(
            coach=self.coach,
            date=date.today() + timedelta(days=days_ahead),
            start_time=time(10, 0),
            end_time=time(11, 0),
            session_type='group',
            duration_minutes=60,
            max_participants=max_participants,
            current_participants=current_participants,
            price_override=price_override,
            status=status,
        )
        block.catalog_session_types.add(session_type)
        return block

    def _create_client_package(self, package=None, player=None,
                               sessions_remaining=4, status='active'):
        """Create a ClientPackage (purchased by the client)."""
        if package is None:
            package = self.package_basic
        return ClientPackage.objects.create(
            client=self.client_profile,
            package=package,
            player=player,
            start_date=date.today(),
            expiry_date=date.today() + timedelta(weeks=4),
            sessions_remaining=sessions_remaining,
            sessions_used=0,
            status=status,
        )

    def _post_booking(self, bookings_data):
        """Post booking request and return parsed JSON response."""
        response = self.http_client.post(
            self.URL,
            data=json.dumps({'bookings': bookings_data}),
            content_type='application/json',
        )
        return response.json()


class TestFreeSession(BookingValidationTestCase):
    """1. Free session - block with price_override=0."""

    def test_free_session_no_package_needed(self):
        """Block with price_override=0 creates booking immediately without package."""
        block = self._create_block(price_override=Decimal('0.00'))

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertTrue(result['success'])
        self.assertEqual(result['bookings_created'], 1)
        self.assertNotIn('requires_payment', result)

        # Verify the booking was created with correct payment_status
        booking = Booking.objects.get(player=self.player_noah)
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual(booking.payment_status, 'paid')
        self.assertIsNone(booking.client_package)


class TestPlayerSpecificPackage(BookingValidationTestCase):
    """2. Session covered by player-specific package."""

    def test_player_package_deducted(self):
        """Player-assigned package is used and session deducted."""
        pkg = self._create_client_package(player=self.player_noah, sessions_remaining=4)
        block = self._create_block()

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertTrue(result['success'])
        self.assertEqual(result['bookings_created'], 1)
        self.assertNotIn('requires_payment', result)

        # Verify package session deducted
        pkg.refresh_from_db()
        self.assertEqual(pkg.sessions_remaining, 3)
        self.assertEqual(pkg.sessions_used, 1)

        # Verify booking linked to package
        booking = Booking.objects.get(player=self.player_noah)
        self.assertEqual(booking.client_package, pkg)
        self.assertEqual(booking.payment_status, 'package')


class TestFamilyPackageFallback(BookingValidationTestCase):
    """3. Session covered by unassigned (family) package."""

    def test_unassigned_package_used_as_fallback(self):
        """Client's unassigned package is used when no player-specific package exists."""
        # No player-specific package - create unassigned one
        pkg = self._create_client_package(player=None, sessions_remaining=4)
        block = self._create_block()

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertTrue(result['success'])
        self.assertEqual(result['bookings_created'], 1)
        self.assertNotIn('requires_payment', result)

        pkg.refresh_from_db()
        self.assertEqual(pkg.sessions_remaining, 3)

        booking = Booking.objects.get(player=self.player_noah)
        self.assertEqual(booking.client_package, pkg)
        self.assertEqual(booking.payment_status, 'package')


class TestPackageNotLinked(BookingValidationTestCase):
    """4. Package not linked to session type - requires payment."""

    def test_unlinked_package_requires_payment(self):
        """Client has basic package but elite session requires elite package."""
        # Client has a basic package (not in linked_packages of elite session)
        self._create_client_package(
            package=self.package_basic, player=self.player_noah, sessions_remaining=4
        )
        # Block uses the elite training session type (linked to elite package only)
        block = self._create_block(session_type=self.session_type_linked)

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertTrue(result['success'])
        self.assertTrue(result['requires_payment'])
        self.assertEqual(result['bookings_created'], 0)
        self.assertEqual(len(result['pending_payment']), 1)
        self.assertEqual(result['pending_payment'][0]['session_type'], 'Elite Training')


class TestDropInOnly(BookingValidationTestCase):
    """5. Session type with allow_package=False (drop-in only)."""

    def test_dropin_always_requires_payment(self):
        """Pick-Up Game (allow_package=False) always requires payment regardless of packages."""
        # Client has an active package with sessions remaining
        self._create_client_package(player=self.player_noah, sessions_remaining=4)
        block = self._create_block(session_type=self.session_type_dropin)

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertTrue(result['success'])
        self.assertTrue(result['requires_payment'])
        self.assertEqual(result['bookings_created'], 0)
        self.assertEqual(len(result['pending_payment']), 1)
        self.assertEqual(result['pending_payment'][0]['session_type'], 'Pick-Up Game')


class TestPackageExhausted(BookingValidationTestCase):
    """6. Package exhausted - sessions_remaining=0."""

    def test_exhausted_package_requires_payment(self):
        """Package with 0 sessions remaining triggers payment requirement."""
        # Package with 0 sessions remaining (but still active status)
        self._create_client_package(
            player=self.player_noah, sessions_remaining=0, status='active'
        )
        block = self._create_block()

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertTrue(result['success'])
        self.assertTrue(result['requires_payment'])
        self.assertEqual(result['bookings_created'], 0)
        self.assertEqual(len(result['pending_payment']), 1)


class TestMixedCart(BookingValidationTestCase):
    """7. Mixed cart: package + drop-in."""

    def test_mixed_cart_partial_package_partial_payment(self):
        """One item covered by package (booked), one drop-in (pending payment)."""
        self._create_client_package(player=self.player_noah, sessions_remaining=4)

        # Two different blocks: one group (uses package), one pickup (drop-in)
        block_group = self._create_block(
            session_type=self.session_type_group, days_ahead=3
        )
        block_pickup = self._create_block(
            session_type=self.session_type_dropin, days_ahead=4
        )

        result = self._post_booking([
            {'block_id': block_group.id, 'player_id': self.player_noah.id},
            {'block_id': block_pickup.id, 'player_id': self.player_noah.id},
        ])

        self.assertTrue(result['success'])
        self.assertTrue(result['requires_payment'])
        # Group session was booked immediately via package
        self.assertEqual(result['bookings_created'], 1)
        # Drop-in session requires payment
        self.assertEqual(len(result['pending_payment']), 1)
        self.assertEqual(result['pending_payment'][0]['session_type'], 'Pick-Up Game')

        # Verify actual booking created
        bookings = Booking.objects.filter(player=self.player_noah)
        self.assertEqual(bookings.count(), 1)
        self.assertEqual(bookings.first().payment_status, 'package')


class TestOverBookingPackage(BookingValidationTestCase):
    """8. Over-booking: more sessions than package allows."""

    def test_package_partially_covers_batch(self):
        """Package has 2 sessions left, booking 4 -> first 2 use package, last 2 require payment."""
        self._create_client_package(player=self.player_noah, sessions_remaining=2)

        # Create 4 blocks
        blocks = []
        for i in range(4):
            blocks.append(self._create_block(days_ahead=3 + i))

        result = self._post_booking([
            {'block_id': b.id, 'player_id': self.player_noah.id}
            for b in blocks
        ])

        self.assertTrue(result['success'])
        self.assertTrue(result['requires_payment'])
        # First 2 use package
        self.assertEqual(result['bookings_created'], 2)
        # Last 2 require payment
        self.assertEqual(len(result['pending_payment']), 2)

        # Verify package fully exhausted
        pkg = ClientPackage.objects.get(
            client=self.client_profile, player=self.player_noah
        )
        self.assertEqual(pkg.sessions_remaining, 0)
        self.assertEqual(pkg.sessions_used, 2)
        self.assertEqual(pkg.status, 'exhausted')


class TestMultiplePlayersDifferentPackages(BookingValidationTestCase):
    """9. Multiple players, different packages."""

    def test_noah_uses_package_ethan_requires_payment(self):
        """Noah has player-assigned package, Ethan does not."""
        # Noah gets a player-specific package
        self._create_client_package(player=self.player_noah, sessions_remaining=4)
        # No package for Ethan

        block_noah = self._create_block(days_ahead=3)
        block_ethan = self._create_block(days_ahead=4)

        result = self._post_booking([
            {'block_id': block_noah.id, 'player_id': self.player_noah.id},
            {'block_id': block_ethan.id, 'player_id': self.player_ethan.id},
        ])

        self.assertTrue(result['success'])
        self.assertTrue(result['requires_payment'])
        # Noah's booking created via package
        self.assertEqual(result['bookings_created'], 1)
        # Ethan needs payment
        self.assertEqual(len(result['pending_payment']), 1)
        self.assertEqual(
            result['pending_payment'][0]['player_name'], 'Ethan Johnson'
        )

    def test_family_package_covers_both_players(self):
        """Unassigned family package covers both Noah and Ethan."""
        # Family package (no player assigned) with enough sessions
        self._create_client_package(player=None, sessions_remaining=4)

        block_noah = self._create_block(days_ahead=3)
        block_ethan = self._create_block(days_ahead=4)

        result = self._post_booking([
            {'block_id': block_noah.id, 'player_id': self.player_noah.id},
            {'block_id': block_ethan.id, 'player_id': self.player_ethan.id},
        ])

        self.assertTrue(result['success'])
        self.assertNotIn('requires_payment', result)
        self.assertEqual(result['bookings_created'], 2)

        # Verify both sessions deducted from same package
        pkg = ClientPackage.objects.get(
            client=self.client_profile, player__isnull=True
        )
        self.assertEqual(pkg.sessions_remaining, 2)
        self.assertEqual(pkg.sessions_used, 2)


class TestBlockFullyBooked(BookingValidationTestCase):
    """10. Block fully booked (is_available=False)."""

    def test_fully_booked_returns_error(self):
        """Block with current_participants >= max_participants returns error."""
        block = self._create_block(max_participants=1, current_participants=1)

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertFalse(result['success'])
        self.assertIn('no longer available', result['error'])

    def test_status_booked_returns_error(self):
        """Block with status='booked' returns error."""
        block = self._create_block(status='booked')

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertFalse(result['success'])
        self.assertIn('no longer available', result['error'])


class TestWaiverRequired(BookingValidationTestCase):
    """11. Waiver required - client without waiver gets blocked."""

    def test_no_waiver_blocks_booking(self):
        """Client without valid waiver cannot book."""
        # Remove the waiver created in setUp
        ClientWaiver.objects.filter(client=self.client_profile).delete()

        block = self._create_block()

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertFalse(result['success'])
        self.assertIn('waiver', result['error'].lower())

    def test_expired_waiver_version_blocks_booking(self):
        """Waiver with old version string does not count as current."""
        ClientWaiver.objects.filter(client=self.client_profile).delete()
        ClientWaiver.objects.create(
            client=self.client_profile,
            full_name='Sarah Johnson',
            signature_text='Sarah Johnson',
            waiver_version='2025-v1',  # old version
            valid_year=timezone.now().year,
        )

        block = self._create_block()

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertFalse(result['success'])
        self.assertIn('waiver', result['error'].lower())

    def test_staff_user_exempt_from_waiver(self):
        """Staff/owner users are exempt from waiver requirement."""
        # Remove waiver
        ClientWaiver.objects.filter(client=self.client_profile).delete()
        # Make user staff
        self.user.is_staff = True
        self.user.save()

        block = self._create_block(price_override=Decimal('0.00'))

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertTrue(result['success'])
        self.assertEqual(result['bookings_created'], 1)

    def test_coach_user_exempt_from_waiver(self):
        """Coach users are exempt from waiver requirement."""
        # Remove waiver and make user a coach
        ClientWaiver.objects.filter(client=self.client_profile).delete()
        Coach.objects.create(
            user=self.user,
            slug='sarah-coach',
            bio='Also a coach',
            hourly_rate=Decimal('50.00'),
            is_active=True,
            profile_enabled=True,
        )

        block = self._create_block(price_override=Decimal('0.00'))

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertTrue(result['success'])
        self.assertEqual(result['bookings_created'], 1)


class TestEdgeCases(BookingValidationTestCase):
    """Additional edge cases for robustness."""

    def test_missing_block_id_returns_error(self):
        """Request with missing block_id returns error."""
        result = self._post_booking([
            {'player_id': self.player_noah.id}
        ])

        self.assertFalse(result['success'])
        self.assertIn('Missing', result['error'])

    def test_missing_player_id_returns_error(self):
        """Request with missing player_id returns error."""
        block = self._create_block()
        result = self._post_booking([
            {'block_id': block.id}
        ])

        self.assertFalse(result['success'])
        self.assertIn('Missing', result['error'])

    def test_invalid_block_id_returns_error(self):
        """Non-existent block_id returns error."""
        result = self._post_booking([
            {'block_id': 99999, 'player_id': self.player_noah.id}
        ])

        self.assertFalse(result['success'])
        self.assertIn('Invalid', result['error'])

    def test_other_clients_player_returns_error(self):
        """Cannot book with another client's player."""
        other_user = User.objects.create_user(
            username='other', email='other@example.com', password='pass'
        )
        other_client = Client.objects.create(user=other_user, client_type='parent')
        other_player = Player.objects.create(
            client=other_client,
            first_name='Other',
            last_name='Kid',
            birth_year=2013,
            gender='F',
            is_active=True,
        )

        block = self._create_block()

        result = self._post_booking([
            {'block_id': block.id, 'player_id': other_player.id}
        ])

        self.assertFalse(result['success'])
        self.assertIn('Invalid', result['error'])

    def test_empty_bookings_list_returns_error(self):
        """Empty bookings list returns error."""
        result = self._post_booking([])

        self.assertFalse(result['success'])
        self.assertIn('No bookings', result['error'])

    def test_block_without_session_type_returns_error(self):
        """Block with no catalog_session_types returns error."""
        block = ScheduleBlock.objects.create(
            coach=self.coach,
            date=date.today() + timedelta(days=5),
            start_time=time(14, 0),
            end_time=time(15, 0),
            session_type='group',
            duration_minutes=60,
            max_participants=10,
            current_participants=0,
            status='available',
        )
        # Deliberately do NOT add catalog_session_types

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertFalse(result['success'])
        self.assertIn('no session type', result['error'].lower())

    def test_block_participants_incremented_after_booking(self):
        """Verify current_participants is incremented when booking is created."""
        self._create_client_package(player=self.player_noah, sessions_remaining=4)
        block = self._create_block(max_participants=5, current_participants=0)

        self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        block.refresh_from_db()
        self.assertEqual(block.current_participants, 1)

    def test_block_status_set_to_booked_when_full(self):
        """Block status becomes 'booked' when last spot is taken."""
        self._create_client_package(player=self.player_noah, sessions_remaining=4)
        block = self._create_block(max_participants=1, current_participants=0)

        self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        block.refresh_from_db()
        self.assertEqual(block.status, 'booked')
        self.assertEqual(block.current_participants, 1)

    def test_linked_package_match_allows_booking(self):
        """Client with elite package can book elite session (linked)."""
        # Client has elite package (which IS in linked_packages for elite session)
        self._create_client_package(
            package=self.package_elite, player=self.player_noah, sessions_remaining=10
        )
        block = self._create_block(session_type=self.session_type_linked)

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertTrue(result['success'])
        self.assertNotIn('requires_payment', result)
        self.assertEqual(result['bookings_created'], 1)

    def test_session_type_with_no_linked_packages_accepts_any_package(self):
        """Session type without linked_packages restriction accepts any package."""
        # session_type_group has no linked_packages set
        self.assertEqual(self.session_type_group.linked_packages.count(), 0)
        self._create_client_package(
            package=self.package_basic, player=self.player_noah, sessions_remaining=4
        )
        block = self._create_block(session_type=self.session_type_group)

        result = self._post_booking([
            {'block_id': block.id, 'player_id': self.player_noah.id}
        ])

        self.assertTrue(result['success'])
        self.assertNotIn('requires_payment', result)
        self.assertEqual(result['bookings_created'], 1)
