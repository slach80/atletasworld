"""
Pytest configuration and fixtures for Atletas Performance Center tests.
"""
import pytest
from django.contrib.auth.models import User, Group
from django.utils import timezone
from datetime import date, time, timedelta

from clients.models import Client, Player, Package, ClientPackage, BookingPreference, NotificationPreference
from coaches.models import Coach, Availability, ScheduleBlock, PlayerAssessment
from bookings.models import Booking


@pytest.fixture
def admin_user(db):
    """Create an admin user."""
    user = User.objects.create_superuser(
        username='admin',
        email='admin@atletasperformancecenter.com',
        password='admin123',
        first_name='Admin',
        last_name='User'
    )
    return user


@pytest.fixture
def client_user(db):
    """Create a regular client user."""
    user = User.objects.create_user(
        username='testclient',
        email='client@example.com',
        password='testpass123',
        first_name='John',
        last_name='Smith'
    )
    return user


@pytest.fixture
def coach_user(db):
    """Create a coach user."""
    user = User.objects.create_user(
        username='testcoach',
        email='coach@atletasperformancecenter.com',
        password='testpass123',
        first_name='Mirko',
        last_name='Test'
    )
    return user


@pytest.fixture
def client_profile(db, client_user):
    """Create a client profile."""
    client = Client.objects.create(
        user=client_user,
        client_type='parent',
        phone='555-0123',
        address='123 Test St, Test City',
        emergency_contact='Jane Smith',
        emergency_phone='555-0124'
    )
    return client


@pytest.fixture
def player(db, client_profile):
    """Create a player profile."""
    player = Player.objects.create(
        client=client_profile,
        first_name='Tommy',
        last_name='Smith',
        birth_year=2012,
        gender='M',
        soccer_club='Test FC',
        team_name='U12 Boys',
        skill_level='intermediate',
        primary_position='midfielder',
        is_active=True
    )
    return player


@pytest.fixture
def coach(db, coach_user):
    """Create a coach profile."""
    coach = Coach.objects.create(
        user=coach_user,
        slug='mirko-test',
        bio='Test coach bio',
        specializations='Technical, Tactical',
        certifications='USSF C License',
        hourly_rate=75.00,
        is_active=True,
        profile_enabled=True,
        tagline='Dedicated to player development',
        experience_years=10
    )
    return coach


@pytest.fixture
def availability(db, coach):
    """Create a coach availability slot."""
    avail = Availability.objects.create(
        coach=coach,
        day_of_week=0,  # Monday
        start_time=time(9, 0),
        end_time=time(17, 0),
        is_active=True
    )
    return avail


@pytest.fixture
def schedule_block(db, coach):
    """Create a schedule block for booking."""
    block = ScheduleBlock.objects.create(
        coach=coach,
        date=date.today() + timedelta(days=1),
        start_time=time(10, 0),
        end_time=time(11, 0),
        session_type='private',
        duration_minutes=60,
        max_participants=1,
        current_participants=0,
        status='available'
    )
    return block


@pytest.fixture
def package_basic4(db):
    """Create a basic 4-session package."""
    pkg = Package.objects.create(
        name='Basic 4 Sessions',
        package_type='basic4',
        description='4 training sessions over 4 weeks',
        price=200.00,
        sessions_included=4,
        validity_weeks=4,
        is_active=True
    )
    return pkg


@pytest.fixture
def package_unlimited(db):
    """Create an unlimited package."""
    pkg = Package.objects.create(
        name='Unlimited Package',
        package_type='unlimited',
        description='Unlimited sessions for 12 weeks',
        price=500.00,
        sessions_included=0,
        validity_weeks=12,
        is_active=True
    )
    return pkg


@pytest.fixture
def client_package(db, client_profile, package_basic4):
    """Create a client package purchase."""
    from datetime import date
    client_pkg = ClientPackage.objects.create(
        client=client_profile,
        package=package_basic4,
        start_date=date.today(),
        expiry_date=date.today() + timedelta(weeks=4),
        sessions_remaining=4,
        sessions_used=0,
        status='active'
    )
    return client_pkg


@pytest.fixture
def booking(db, client_package, schedule_block, player):
    """Create a booking."""
    booking = Booking.objects.create(
        client_package=client_package,
        schedule_block=schedule_block,
        player=player,
        amount_paid=50.00,
        status='confirmed'
    )
    return booking


@pytest.fixture
def booking_preference(db, client_profile, coach):
    """Create booking preferences for a client."""
    prefs = BookingPreference.objects.create(
        client=client_profile,
        preferred_days=['monday', 'wednesday', 'friday'],
        preferred_time_slots=['afternoon', 'evening'],
        auto_filter=True
    )
    prefs.favorite_coaches.add(coach)
    return prefs


@pytest.fixture
def notification_preference(db, client_profile):
    """Create notification preferences for a client."""
    prefs = NotificationPreference.objects.create(
        client=client_profile,
        booking_confirmations='email',
        booking_reminders='email',
        booking_cancellations='both',
        reminder_hours_before=24
    )
    return prefs


@pytest.fixture
def player_assessment(db, booking, coach, player):
    """Create a player assessment."""
    assessment = PlayerAssessment.objects.create(
        booking=booking,
        coach=coach,
        player=player,
        training_type='technical',
        effort_engagement=4,
        technical_proficiency=3,
        tactical_awareness=3,
        physical_performance=4,
        goals_achievement=4,
        focus_areas='Improve first touch',
        highlights='Great effort today',
        parent_visible_notes='Excellent progress on passing'
    )
    return assessment
