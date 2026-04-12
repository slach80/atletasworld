"""
Pytest configuration and fixtures for Atletas Performance Center tests.

Fixtures are grouped by domain:
  - Users & auth:     admin_user, client_user, coach_user
  - Client domain:    client_profile, player, package_basic4, package_unlimited,
                      client_package, booking_preference, notification_preference,
                      discount_code
  - Coach domain:     coach, availability, schedule_block, player_assessment
  - Booking domain:   session_type_group, availability_slot, pending_booking
  - Other domains:    review, daily_metrics
"""
import pytest
from decimal import Decimal
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
def booking(db, client_package, coach, player, schedule_block):
    """Create a confirmed booking with all required fields."""
    return Booking.objects.create(
        client=client_package.client,
        coach=coach,
        scheduled_date=date.today() + timedelta(days=1),
        scheduled_time=time(10, 0),
        duration_minutes=60,
        client_package=client_package,
        player=player,
        amount_paid=Decimal('50.00'),
        payment_status='package',
        status='confirmed',
    )


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


# ── Booking-domain fixtures ───────────────────────────────────────────────────

@pytest.fixture
def session_type_group(db):
    """Group session type used as a base for AvailabilitySlot and Booking tests."""
    from bookings.models import SessionType
    return SessionType.objects.create(
        name='Group Training',
        session_format='group',
        duration_minutes=60,
        price=Decimal('40.00'),
        max_participants=10,
        is_active=True,
    )


@pytest.fixture
def availability_slot(db, coach, session_type_group):
    """AvailabilitySlot with 5 spots, scheduled 3 days out."""
    from bookings.models import AvailabilitySlot
    return AvailabilitySlot.objects.create(
        coach=coach,
        session_type=session_type_group,
        date=date.today() + timedelta(days=3),
        start_time=time(14, 0),
        end_time=time(15, 0),
        max_bookings=5,
        current_bookings=0,
        status='available',
    )


@pytest.fixture
def pending_booking(db, client_profile, coach, session_type_group, availability_slot):
    """A pending Booking scheduled 3 days out (safe for cancel/reschedule tests)."""
    return Booking.objects.create(
        client=client_profile,
        coach=coach,
        session_type=session_type_group,
        availability_slot=availability_slot,
        scheduled_date=date.today() + timedelta(days=3),
        scheduled_time=time(14, 0),
        duration_minutes=60,
        status='pending',
        payment_status='pending',
        amount_paid=Decimal('0.00'),
    )


@pytest.fixture
def near_term_booking(db, client_profile, coach, session_type_group):
    """A confirmed Booking scheduled only 1 hour from now — cannot be cancelled."""
    from django.utils import timezone as tz
    now = tz.now()
    return Booking.objects.create(
        client=client_profile,
        coach=coach,
        session_type=session_type_group,
        scheduled_date=now.date(),
        scheduled_time=(now + timedelta(hours=1)).time(),
        duration_minutes=60,
        status='confirmed',
        payment_status='pending',
        amount_paid=Decimal('0.00'),
    )


# ── Other-domain fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def discount_code(db):
    """A 10% percentage-off discount code valid indefinitely."""
    from clients.models import DiscountCode
    return DiscountCode.objects.create(
        code='TEST10',
        description='10% off everything',
        discount_type='percent',
        value=Decimal('10.00'),
        scope='all',
        is_active=True,
    )


@pytest.fixture
def review(db, client_profile, coach, pending_booking):
    """A 5-star review linking a client, coach, and booking."""
    from reviews.models import Review
    return Review.objects.create(
        client=client_profile,
        coach=coach,
        booking=pending_booking,
        rating=5,
        comment='Excellent session!',
        is_featured=False,
        is_approved=True,
    )


@pytest.fixture
def daily_metrics(db):
    """DailyMetrics record for today."""
    from analytics.models import DailyMetrics
    return DailyMetrics.objects.create(
        date=date.today(),
        total_bookings=5,
        completed_sessions=3,
        cancelled_sessions=1,
        new_clients=2,
        total_revenue=Decimal('200.00'),
    )
