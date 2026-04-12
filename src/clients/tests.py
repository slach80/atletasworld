"""
Tests for clients models.
"""
import pytest
from datetime import date, timedelta
from django.utils import timezone
from django.core.exceptions import ValidationError

from clients.models import (
    Client, Player, Package, ClientPackage,
    BookingPreference, NotificationPreference, Notification
)


@pytest.mark.unit
class TestClientModel:
    """Test cases for Client model."""

    def test_client_creation(self, client_profile, client_user):
        """Test that a client profile is created correctly."""
        assert client_profile.user == client_user
        assert client_profile.client_type == 'parent'
        assert client_profile.phone == '555-0123'
        assert str(client_profile) == 'John Smith'

    def test_client_string_representation(self, client_profile):
        """Test the string representation of a client."""
        assert str(client_profile) == client_profile.user.get_full_name()


@pytest.mark.unit
class TestPlayerModel:
    """Test cases for Player model."""

    def test_player_creation(self, player, client_profile):
        """Test that a player profile is created correctly."""
        assert player.client == client_profile
        assert player.first_name == 'Tommy'
        assert player.last_name == 'Smith'
        assert player.birth_year == 2012
        assert player.gender == 'M'
        assert player.skill_level == 'intermediate'

    def test_player_age_property(self, player):
        """Test the age property calculation."""
        expected_age = timezone.now().year - player.birth_year
        assert player.age == expected_age

    def test_player_age_group_property(self, player):
        """Test the age group property."""
        age = player.age
        if age <= 6:
            assert player.age_group == 'U6'
        elif age <= 8:
            assert player.age_group == 'U8'
        elif age <= 10:
            assert player.age_group == 'U10'
        elif age <= 12:
            assert player.age_group == 'U12'
        elif age <= 14:
            assert player.age_group == 'U14'
        elif age <= 16:
            assert player.age_group == 'U16'
        elif age <= 19:
            assert player.age_group == 'U19'
        else:
            assert player.age_group == 'Adult'

    def test_player_string_representation(self, player):
        """Test the string representation of a player."""
        expected = f"{player.first_name} {player.last_name} ({player.birth_year})"
        assert str(player) == expected

    def test_player_is_active_default(self, player):
        """Test that players are active by default."""
        assert player.is_active is True


@pytest.mark.unit
class TestPackageModel:
    """Test cases for Package model."""

    def test_package_creation(self, package_basic4):
        """Test that a package is created correctly."""
        assert package_basic4.name == 'Basic 4 Sessions'
        assert package_basic4.package_type == 'basic4'
        assert package_basic4.price == 200.00
        assert package_basic4.sessions_included == 4
        assert package_basic4.validity_weeks == 4

    def test_package_is_event_package(self, package_basic4):
        """Test the is_event_package property."""
        assert package_basic4.is_event_package is False

        # Create an event package
        event_pkg = Package.objects.create(
            name='Special Event',
            package_type='special',
            price=100.00,
            sessions_included=1,
            validity_weeks=1,
            is_special=True,
            event_start_date=date.today(),
            event_end_date=date.today() + timedelta(days=1)
        )
        assert event_pkg.is_event_package is True

    def test_package_string_representation(self, package_basic4):
        """Test the string representation of a package."""
        assert str(package_basic4) == f"{package_basic4.name} - ${package_basic4.price}"

    def test_package_spots_remaining(self, db):
        """Test the spots_remaining property for event packages."""
        # Create limited event package
        limited_pkg = Package.objects.create(
            name='Limited Event',
            package_type='special',
            price=100.00,
            sessions_included=1,
            validity_weeks=1,
            is_special=True,
            event_start_date=date.today(),
            event_end_date=date.today() + timedelta(days=1),
            max_participants=10
        )
        assert limited_pkg.spots_remaining == 10

        # Unlimited package should return None
        unlimited_pkg = Package.objects.create(
            name='Unlimited Event',
            package_type='special',
            price=100.00,
            sessions_included=1,
            validity_weeks=1,
            is_special=True,
            max_participants=0
        )
        assert unlimited_pkg.spots_remaining is None


@pytest.mark.unit
class TestClientPackageModel:
    """Test cases for ClientPackage model."""

    def test_client_package_creation(self, client_package, client_profile, package_basic4):
        """Test that a client package purchase is created correctly."""
        assert client_package.client == client_profile
        assert client_package.package == package_basic4
        assert client_package.sessions_remaining == 4
        assert client_package.status == 'active'

    def test_client_package_is_valid(self, client_package):
        """Test the is_valid property."""
        assert client_package.is_valid is True

    def test_client_package_invalid_status(self, client_package):
        """Test that expired status makes package invalid."""
        client_package.status = 'expired'
        client_package.save()
        assert client_package.is_valid is False

    def test_client_package_invalid_expiry(self, client_package):
        """Test that past expiry date makes package invalid."""
        client_package.expiry_date = date.today() - timedelta(days=1)
        client_package.save()
        assert client_package.is_valid is False

    def test_client_package_invalid_sessions(self, client_package):
        """Test that zero sessions makes package invalid."""
        client_package.sessions_remaining = 0
        client_package.save()
        assert client_package.is_valid is False

    def test_use_session(self, client_package):
        """Test using a session from the package."""
        initial_remaining = client_package.sessions_remaining
        initial_used = client_package.sessions_used

        client_package.use_session()
        client_package.refresh_from_db()

        assert client_package.sessions_remaining == initial_remaining - 1
        assert client_package.sessions_used == initial_used + 1

    def test_use_session_exhausts_package(self, client_package):
        """Test that using last session exhausts the package."""
        client_package.sessions_remaining = 1
        client_package.save()

        client_package.use_session()
        client_package.refresh_from_db()

        assert client_package.status == 'exhausted'
        assert client_package.sessions_remaining == 0

    def test_use_session_unlimited_package(self, package_unlimited, client_profile):
        """Test using sessions with unlimited package."""
        unlimited_client_pkg = ClientPackage.objects.create(
            client=client_profile,
            package=package_unlimited,
            start_date=date.today(),
            expiry_date=date.today() + timedelta(weeks=12),
            sessions_remaining=0,
            status='active'
        )

        # Should not decrement sessions_remaining for unlimited
        unlimited_client_pkg.use_session()
        unlimited_client_pkg.refresh_from_db()

        assert unlimited_client_pkg.sessions_remaining == 0

    def test_calculate_upgrade_cost_valid_package(self, client_package):
        """Test upgrade cost calculation for a valid package."""
        # Create a more expensive package
        better_pkg = Package.objects.create(
            name='Elite Package',
            package_type='elite24',
            price=500.00,
            sessions_included=24,
            validity_weeks=12
        )

        upgrade_cost = client_package.calculate_upgrade_cost(better_pkg)

        # Should be less than full price since client has remaining sessions
        assert upgrade_cost > 0
        assert upgrade_cost < better_pkg.price

    def test_calculate_upgrade_cost_invalid_package(self, client_package):
        """Test that invalid package returns full price."""
        client_package.status = 'expired'
        client_package.save()

        better_pkg = Package.objects.create(
            name='Elite Package',
            package_type='elite24',
            price=500.00,
            sessions_included=24,
            validity_weeks=12
        )

        upgrade_cost = client_package.calculate_upgrade_cost(better_pkg)
        assert upgrade_cost == float(better_pkg.price)

    def test_get_upgrade_options(self, client_package):
        """Test getting available upgrade options."""
        # Create a more expensive package
        Package.objects.create(
            name='Elite Package',
            package_type='elite24',
            price=500.00,
            sessions_included=24,
            validity_weeks=12
        )

        upgrades = client_package.get_upgrade_options()

        assert len(upgrades) >= 1
        assert all(u['upgrade_cost'] > 0 for u in upgrades)

    def test_client_package_string_representation(self, client_package):
        """Test the string representation of a client package."""
        expected = f"{client_package.client} - {client_package.package.name} ({client_package.status})"
        assert str(client_package) == expected


@pytest.mark.unit
class TestBookingPreferenceModel:
    """Test cases for BookingPreference model."""

    def test_booking_preference_creation(self, booking_preference, client_profile, coach):
        """Test that booking preferences are created correctly."""
        assert booking_preference.client == client_profile
        assert list(booking_preference.favorite_coaches.all()) == [coach]
        assert booking_preference.preferred_days == ['monday', 'wednesday', 'friday']
        assert booking_preference.auto_filter is True

    def test_booking_preference_string_representation(self, booking_preference):
        """Test the string representation."""
        expected = f"Booking preferences for {booking_preference.client}"
        assert str(booking_preference) == expected


@pytest.mark.unit
class TestNotificationPreferenceModel:
    """Test cases for NotificationPreference model."""

    def test_notification_preference_creation(self, notification_preference, client_profile):
        """Test that notification preferences are created correctly."""
        assert notification_preference.client == client_profile
        assert notification_preference.booking_confirmations == 'email'
        assert notification_preference.reminder_hours_before == 24

    def test_notification_preference_string_representation(self, notification_preference):
        """Test the string representation."""
        expected = f"Notification preferences for {notification_preference.client}"
        assert str(notification_preference) == expected


@pytest.mark.unit
class TestNotificationModel:
    """Test cases for Notification model."""

    def test_notification_creation(self, client_profile):
        """Test that notifications are created correctly."""
        notification = Notification.objects.create(
            client=client_profile,
            notification_type='booking_confirmed',
            title='Booking Confirmed',
            message='Your booking has been confirmed.',
            method='email',
            status='pending'
        )

        assert notification.client == client_profile
        assert notification.notification_type == 'booking_confirmed'
        assert notification.status == 'pending'

    def test_notification_string_representation(self, client_profile):
        """Test the string representation."""
        notification = Notification.objects.create(
            client=client_profile,
            notification_type='booking_confirmed',
            title='Booking Confirmed',
            message='Test message',
            method='email',
            status='pending'
        )

        expected = f"{notification.get_notification_type_display()} - {client_profile}"
        assert str(notification) == expected


# ── Client approval workflow ──────────────────────────────────────────────────

@pytest.mark.unit
class TestClientApproval:
    """Tests for Client.needs_approval and Client.is_approved property logic.

    Coaches and renters require explicit owner approval before they can access
    services. The is_approved property also respects optional term_start/term_end
    datetime bounds.
    """

    def test_needs_approval_true_for_coach_type(self, db, client_user):
        """Clients with client_type='coach' must go through the approval workflow."""
        client = Client.objects.create(user=client_user, client_type='coach')
        assert client.needs_approval is True

    def test_needs_approval_true_for_renter_type(self, db, coach_user):
        """Clients with client_type='renter' must go through the approval workflow."""
        client = Client.objects.create(user=coach_user, client_type='renter')
        assert client.needs_approval is True

    def test_needs_approval_false_for_parent_type(self, client_profile):
        """Standard parent/guardian accounts do not require owner approval."""
        assert client_profile.needs_approval is False

    def test_is_approved_false_when_status_pending(self, client_profile):
        """Client with approval_status='pending' should not be considered approved."""
        client_profile.approval_status = 'pending'
        assert client_profile.is_approved is False

    def test_is_approved_true_when_approved_with_no_term(self, client_profile):
        """Approved client with no term dates should be considered fully approved."""
        client_profile.approval_status = 'approved'
        client_profile.term_start = None
        client_profile.term_end = None
        assert client_profile.is_approved is True

    def test_is_approved_false_when_term_expired(self, client_profile):
        """Approved client whose term_end is in the past should not be approved."""
        from django.utils import timezone
        from datetime import timedelta
        client_profile.approval_status = 'approved'
        client_profile.term_end = timezone.now() - timedelta(days=1)
        assert client_profile.is_approved is False

    def test_is_approved_false_when_term_not_started(self, client_profile):
        """Approved client whose term_start is in the future should not yet be approved."""
        from django.utils import timezone
        from datetime import timedelta
        client_profile.approval_status = 'approved'
        client_profile.term_start = timezone.now() + timedelta(days=7)
        assert client_profile.is_approved is False


# ── DiscountCode ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDiscountCode:
    """Tests for DiscountCode validity, scoping, and discount calculations."""

    def test_str_representation(self, discount_code):
        """__str__ should show the code and its discount value."""
        result = str(discount_code)
        assert 'TEST10' in result
        assert '%' in result or 'off' in result.lower()

    def test_is_active_default_true(self, db):
        """Newly created discount codes should be active by default."""
        from clients.models import DiscountCode
        from decimal import Decimal
        dc = DiscountCode.objects.create(
            code='NEWCODE',
            discount_type='percent',
            value=Decimal('5.00'),
        )
        assert dc.is_active is True

    def test_scope_choices_are_valid(self, discount_code):
        """The default scope 'all' should be a valid choice string."""
        assert discount_code.scope in ['all', 'packages', 'sessions']

    def test_is_valid_now_returns_true_when_active(self, discount_code):
        """An active code with no date restrictions should be valid."""
        valid, message = discount_code.is_valid_now()
        assert valid is True
        assert message == ''

    def test_is_valid_now_returns_false_when_expired(self, db):
        """A code past its valid_until date should not be valid."""
        from clients.models import DiscountCode
        from decimal import Decimal
        from datetime import date, timedelta
        dc = DiscountCode.objects.create(
            code='EXPIRED',
            discount_type='percent',
            value=Decimal('10.00'),
            valid_until=date.today() - timedelta(days=1),  # expired yesterday
        )
        valid, message = dc.is_valid_now()
        assert valid is False
        assert 'expired' in message.lower()

    def test_is_valid_now_returns_false_when_inactive(self, db):
        """A code with is_active=False should never be valid."""
        from clients.models import DiscountCode
        from decimal import Decimal
        dc = DiscountCode.objects.create(
            code='INACTIVE',
            discount_type='percent',
            value=Decimal('10.00'),
            is_active=False,
        )
        valid, message = dc.is_valid_now()
        assert valid is False

    def test_percentage_discount_calculation(self, discount_code):
        """compute_discount() should return 10% of the subtotal for a 10% code."""
        from decimal import Decimal
        result = discount_code.compute_discount(Decimal('100.00'))
        assert result == Decimal('10.00')

    def test_fixed_discount_calculation(self, db):
        """compute_discount() with a fixed-dollar code should return the fixed amount."""
        from clients.models import DiscountCode
        from decimal import Decimal
        dc = DiscountCode.objects.create(
            code='SAVE20',
            discount_type='fixed',
            value=Decimal('20.00'),
        )
        result = dc.compute_discount(Decimal('100.00'))
        assert result == Decimal('20.00')

    def test_fixed_discount_capped_at_subtotal(self, db):
        """Fixed-dollar discounts should not exceed the subtotal amount."""
        from clients.models import DiscountCode
        from decimal import Decimal
        dc = DiscountCode.objects.create(
            code='SAVE50',
            discount_type='fixed',
            value=Decimal('50.00'),
        )
        # Subtotal is only $30, discount of $50 should be capped at $30
        result = dc.compute_discount(Decimal('30.00'))
        assert result == Decimal('30.00')


# ── ClientCredit ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestClientCredit:
    """Tests for ClientCredit model — APC Select monthly credits and manual grants."""

    def test_str_representation(self, db, client_profile):
        """__str__ should show client name, amount, type, and status."""
        from clients.models import ClientCredit
        from decimal import Decimal
        credit = ClientCredit.objects.create(
            client=client_profile,
            amount=Decimal('40.00'),
            credit_type='select_monthly',
            status='available',
        )
        result = str(credit)
        assert '40' in result
        assert 'available' in result.lower() or 'Select' in result

    def test_credit_amount_stored_correctly(self, db, client_profile):
        """The credit amount should be stored with full decimal precision."""
        from clients.models import ClientCredit
        from decimal import Decimal
        credit = ClientCredit.objects.create(
            client=client_profile,
            amount=Decimal('40.00'),
            credit_type='manual',
        )
        assert credit.amount == Decimal('40.00')

    def test_is_usable_true_for_available_credit(self, db, client_profile):
        """An available credit with no expiry should be usable."""
        from clients.models import ClientCredit
        from decimal import Decimal
        credit = ClientCredit.objects.create(
            client=client_profile,
            amount=Decimal('40.00'),
            credit_type='manual',
            status='available',
            expires_at=None,
        )
        assert credit.is_usable is True

    def test_is_usable_false_for_applied_credit(self, db, client_profile):
        """An already-applied credit should not be reusable."""
        from clients.models import ClientCredit
        from decimal import Decimal
        credit = ClientCredit.objects.create(
            client=client_profile,
            amount=Decimal('40.00'),
            credit_type='manual',
            status='applied',
        )
        assert credit.is_usable is False

    def test_is_usable_false_for_expired_credit(self, db, client_profile):
        """A credit past its expires_at date should not be usable."""
        from clients.models import ClientCredit
        from decimal import Decimal
        from datetime import date, timedelta
        credit = ClientCredit.objects.create(
            client=client_profile,
            amount=Decimal('40.00'),
            credit_type='manual',
            status='available',
            expires_at=date.today() - timedelta(days=1),
        )
        assert credit.is_usable is False

    def test_ordering_newest_first(self, db, client_profile):
        """Credits should be ordered newest first (Meta ordering = ['-created_at'])."""
        from clients.models import ClientCredit
        from decimal import Decimal
        c1 = ClientCredit.objects.create(client=client_profile, amount=Decimal('10.00'))
        c2 = ClientCredit.objects.create(client=client_profile, amount=Decimal('20.00'))
        credits = list(ClientCredit.objects.filter(pk__in=[c1.pk, c2.pk]))
        assert credits[0].pk == c2.pk  # c2 created later → appears first
