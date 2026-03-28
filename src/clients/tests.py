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
