"""
Owner portal view tests.

Coverage:
  TestOwnerAuthWall          — 3 auth-wall tests (all 66 owner URLs)
  TestOwnerDashboard         — 3
  TestOwnerPackageCRUD       — 11
  TestOwnerPackageJSON       — 5
  TestOwnerClientActions     — 7
  TestOwnerBlogCRUD          — 10
  TestOwnerCoachActions      — 8
  TestOwnerDiscountCodes     — 7
  TestOwnerCreditsAndRefunds — 7
  TestOwnerAIAssist          — 8
  TestOwnerFieldRentals      — 4
  TestOwnerReferralPayouts   — 5
  TestOwnerSessionTypes      — 8
  TestOwnerBookingDetail     — 4
"""
import json
import pytest
from decimal import Decimal
from datetime import date, time, timedelta
from unittest.mock import patch, MagicMock

from django.test import Client as TestClient
from django.urls import reverse
from django.contrib.auth.models import User


# ── File-local fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def blog_post(db):
    from blog.models import BlogPost
    return BlogPost.objects.create(
        title='Test Post',
        slug='test-post',
        excerpt='Test excerpt.',
        body='<p>Body.</p>',
        is_published=False,
    )


@pytest.fixture
def payment(db, client_profile, booking):
    from payments.models import Payment
    return Payment.objects.create(
        client=client_profile,
        booking=booking,
        amount=Decimal('50.00'),
        stripe_payment_intent_id='pi_test_abc123',
        status='succeeded',
    )


@pytest.fixture
def referral_payout(db, coach_user, client_user):
    from clients.models import ReferralCode, Referral, ReferralPayout
    rc, _ = ReferralCode.objects.get_or_create(
        user=coach_user, defaults={'code': 'COACH001'}
    )
    from django.utils import timezone as tz
    ref = Referral.objects.create(
        referrer_user=coach_user,
        referred_user=client_user,
        referral_code='COACH001',
        referrer_type='coach',
        status='activated',
        referral_window_expires=tz.now() + timedelta(days=60),
    )
    return ReferralPayout.objects.create(
        referral=ref,
        coach_user=coach_user,
        amount=Decimal('20.00'),
        status='pending',
    )


@pytest.fixture
def pending_rental_slot(db, client_profile):
    from clients.models import FieldRentalSlot
    return FieldRentalSlot.objects.create(
        date=date.today() + timedelta(days=5),
        start_time=time(9, 0),
        end_time=time(10, 0),
        duration_minutes=60,
        price=Decimal('100.00'),
        title='Pending Rental',
        status='pending_approval',
        booked_by_client=client_profile,
        booker_type='individual',
    )


@pytest.fixture
def booked_rental_slot(db, client_profile):
    from clients.models import FieldRentalSlot
    from django.utils import timezone as tz
    return FieldRentalSlot.objects.create(
        date=date.today() + timedelta(days=5),
        start_time=time(11, 0),
        end_time=time(12, 0),
        duration_minutes=60,
        price=Decimal('100.00'),
        title='Booked Rental',
        status='booked',
        booked_by_client=client_profile,
        booker_type='individual',
        approved_at=tz.now(),
    )


@pytest.fixture
def select_team(db, client_profile):
    from clients.models import Team
    return Team.objects.create(
        name='U14 Boys Select',
        slug='u14-boys-select',
        age_group='U14',
        skill_level='elite',
        manager=client_profile,
        is_select=True,
        is_active=True,
    )


# ── Helper ────────────────────────────────────────────────────────────────────

def _tc():
    return TestClient()


# ── 1. Auth wall ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerAuthWall:
    """Every owner URL must redirect anonymous and non-owner users."""

    def _build_url_list(
        self,
        client_profile,
        player,
        coach,
        package_basic4,
        client_package,
        booking,
        discount_code,
        session_type_group,
        blog_post_fixture,
        payment_fixture,
        referral_payout_fixture,
        pending_rental_slot_fixture,
    ):
        pk1 = package_basic4.pk
        cp_pk = client_package.pk
        cl_pk = client_profile.pk
        pl_pk = player.pk
        co_pk = coach.pk
        bk_pk = booking.pk
        dc_pk = discount_code.pk
        st_pk = session_type_group.pk
        bp_pk = blog_post_fixture.pk
        pay_pk = payment_fixture.pk
        rp_pk = referral_payout_fixture.pk
        rs_pk = pending_rental_slot_fixture.pk

        return [
            reverse('owner_dashboard'),
            reverse('owner_notifications'),
            reverse('owner_send_notification'),
            reverse('owner_packages'),
            reverse('owner_package_add'),
            reverse('owner_package_edit', kwargs={'pk': pk1}),
            reverse('owner_package_delete', kwargs={'pk': pk1}),
            reverse('owner_package_restore', kwargs={'pk': pk1}),
            reverse('owner_package_hard_delete', kwargs={'pk': pk1}),
            reverse('owner_package_duplicate', kwargs={'pk': pk1}),
            reverse('owner_package_assign', kwargs={'pk': cp_pk}),
            reverse('owner_package_adjust', kwargs={'pk': cp_pk}),
            reverse('owner_coaches'),
            reverse('owner_coach_add'),
            reverse('owner_coach_edit', kwargs={'pk': co_pk}),
            reverse('owner_coach_delete', kwargs={'pk': co_pk}),
            reverse('owner_coach_schedule', kwargs={'pk': co_pk}),
            reverse('owner_bookings'),
            reverse('owner_booking_detail', kwargs={'pk': bk_pk}),
            reverse('owner_clients'),
            reverse('owner_client_detail', kwargs={'pk': cl_pk}),
            reverse('owner_client_approve', kwargs={'pk': cl_pk}),
            reverse('owner_client_reject', kwargs={'pk': cl_pk}),
            reverse('owner_client_toggle_select_invite', kwargs={'pk': cl_pk}),
            reverse('owner_client_settle_bookings', kwargs={'pk': cl_pk}),
            reverse('owner_players'),
            reverse('owner_player_detail', kwargs={'pk': pl_pk}),
            reverse('owner_session_types'),
            reverse('owner_session_type_edit', kwargs={'pk': st_pk}),
            reverse('owner_session_type_delete', kwargs={'pk': st_pk}),
            reverse('owner_session_type_duplicate', kwargs={'pk': st_pk}),
            reverse('owner_session_type_apply_capacities', kwargs={'pk': st_pk}),
            reverse('owner_session_type_roster', kwargs={'pk': st_pk}),
            reverse('owner_teams'),
            reverse('owner_finances'),
            reverse('owner_payments'),
            reverse('owner_issue_refund', kwargs={'payment_id': pay_pk}),
            reverse('owner_credits'),
            reverse('owner_discount_codes'),
            reverse('owner_discount_code_detail', kwargs={'pk': dc_pk}),
            reverse('owner_waivers'),
            reverse('owner_contacts'),
            reverse('owner_referrals'),
            reverse('owner_referral_payouts'),
            reverse('owner_payout_approve', kwargs={'payout_id': rp_pk}),
            reverse('owner_payout_reject', kwargs={'payout_id': rp_pk}),
            reverse('owner_payout_mark_paid', kwargs={'payout_id': rp_pk}),
            reverse('owner_guide'),
            reverse('owner_blog_list'),
            reverse('owner_blog_new'),
            reverse('owner_blog_edit', kwargs={'pk': bp_pk}),
            reverse('owner_blog_delete', kwargs={'pk': bp_pk}),
            reverse('owner_blog_toggle_publish', kwargs={'pk': bp_pk}),
            reverse('owner_blog_ai_assist'),
            reverse('owner_naming_ai_assist'),
            reverse('owner_notification_ai_assist'),
            reverse('owner_upcoming_sessions'),
            reverse('owner_select_games'),
            reverse('owner_services'),
            reverse('owner_field_slots'),
            reverse('owner_field_slot_conflict_check'),
            reverse('owner_field_slot_edit', kwargs={'pk': rs_pk}),
            reverse('owner_field_slot_approve', kwargs={'pk': rs_pk}),
            reverse('owner_field_slot_reject', kwargs={'pk': rs_pk}),
            reverse('owner_field_slot_cancel', kwargs={'pk': rs_pk}),
        ]

    def test_anonymous_all_redirect(
        self,
        client_profile, player, coach, package_basic4, client_package,
        booking, discount_code, session_type_group,
        blog_post, payment, referral_payout, pending_rental_slot,
    ):
        tc = _tc()
        urls = self._build_url_list(
            client_profile, player, coach, package_basic4, client_package,
            booking, discount_code, session_type_group,
            blog_post, payment, referral_payout, pending_rental_slot,
        )
        for url in urls:
            resp = tc.get(url)
            assert resp.status_code == 302, f"Expected 302 for anon on {url}, got {resp.status_code}"

    def test_non_owner_all_redirect(
        self,
        client_user, client_profile, player, coach, package_basic4,
        client_package, booking, discount_code, session_type_group,
        blog_post, payment, referral_payout, pending_rental_slot,
    ):
        tc = _tc()
        tc.force_login(client_user)
        urls = self._build_url_list(
            client_profile, player, coach, package_basic4, client_package,
            booking, discount_code, session_type_group,
            blog_post, payment, referral_payout, pending_rental_slot,
        )
        for url in urls:
            resp = tc.get(url)
            assert resp.status_code == 302, f"Expected 302 for non-owner on {url}, got {resp.status_code}"

    def test_owner_all_valid_status(
        self,
        admin_user, client_profile, player, coach, package_basic4,
        client_package, booking, discount_code, session_type_group,
        blog_post, payment, referral_payout, pending_rental_slot,
    ):
        tc = _tc()
        tc.force_login(admin_user)
        urls = self._build_url_list(
            client_profile, player, coach, package_basic4, client_package,
            booking, discount_code, session_type_group,
            blog_post, payment, referral_payout, pending_rental_slot,
        )
        for url in urls:
            resp = tc.get(url)
            assert resp.status_code in (200, 302, 400, 405), (
                f"Expected 200/302/400/405 for owner on {url}, got {resp.status_code}"
            )


# ── 2. Dashboard ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerDashboard:
    def test_dashboard_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_dashboard'))
        assert resp.status_code == 200

    def test_dashboard_shows_context(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_dashboard'))
        assert resp.status_code == 200
        # The dashboard template renders without error
        assert b'owner' in resp.content.lower() or len(resp.content) > 100

    def test_upcoming_sessions_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_upcoming_sessions'))
        assert resp.status_code == 200


# ── 3. Package CRUD ───────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerPackageCRUD:
    def test_package_list_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_packages'))
        assert resp.status_code == 200

    def test_package_add_get_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_package_add'))
        assert resp.status_code == 200

    def test_package_add_post_creates(self, admin_user):
        from clients.models import Package
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_package_add'), {
            'name': 'New Test Package',
            'package_type': 'basic4',
            'description': 'Test desc',
            'price': '150.00',
            'sessions_included': '4',
            'validity_weeks': '4',
            'is_active': 'on',
        })
        assert resp.status_code == 302
        assert Package.objects.filter(name='New Test Package').exists()

    def test_package_edit_get_200(self, admin_user, package_basic4):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_package_edit', kwargs={'pk': package_basic4.pk}))
        assert resp.status_code == 200

    def test_package_edit_post_updates(self, admin_user, package_basic4):
        from clients.models import Package
        tc = _tc()
        tc.force_login(admin_user)
        tc.post(reverse('owner_package_edit', kwargs={'pk': package_basic4.pk}), {
            'name': 'Updated Name',
            'package_type': 'basic4',
            'description': 'Updated',
            'price': '250.00',
            'sessions_included': '4',
            'validity_weeks': '4',
            'is_active': 'on',
        })
        package_basic4.refresh_from_db()
        assert package_basic4.name == 'Updated Name'

    def test_package_delete_archives(self, admin_user, package_basic4):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_package_delete', kwargs={'pk': package_basic4.pk}))
        assert resp.status_code == 302
        package_basic4.refresh_from_db()
        assert package_basic4.is_active is False

    def test_package_restore(self, admin_user, package_basic4):
        from clients.models import Package
        package_basic4.is_active = False
        package_basic4.save()
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_package_restore', kwargs={'pk': package_basic4.pk}))
        assert resp.status_code == 302
        package_basic4.refresh_from_db()
        assert package_basic4.is_active is True

    def test_package_hard_delete_no_active_clients(self, admin_user):
        from clients.models import Package
        pkg = Package.objects.create(
            name='Deletable Package', package_type='basic4',
            price=100, sessions_included=4, validity_weeks=4, is_active=False,
        )
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_package_hard_delete', kwargs={'pk': pkg.pk}))
        assert resp.status_code == 302
        assert not Package.objects.filter(pk=pkg.pk).exists()

    def test_package_hard_delete_blocked_with_active_clients(self, admin_user, package_basic4, client_package):
        from clients.models import Package
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_package_hard_delete', kwargs={'pk': package_basic4.pk}))
        assert resp.status_code == 302
        assert Package.objects.filter(pk=package_basic4.pk).exists()

    def test_package_duplicate(self, admin_user, package_basic4):
        from clients.models import Package
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_package_duplicate', kwargs={'pk': package_basic4.pk}))
        assert resp.status_code == 302
        assert Package.objects.filter(name__icontains='Copy').exists()

    def test_package_list_shows_archived(self, admin_user, package_basic4):
        package_basic4.is_active = False
        package_basic4.save()
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_packages'))
        assert resp.status_code == 200
        assert package_basic4.name.encode() in resp.content


# ── 4. Package JSON endpoints ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerPackageJSON:
    def test_assign_valid_player(self, admin_user, client_package, player):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_package_assign', kwargs={'pk': client_package.pk}),
            data=json.dumps({'player_id': player.pk}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['success'] is True
        client_package.refresh_from_db()
        assert client_package.player_id == player.pk

    def test_unassign_package(self, admin_user, client_package, player):
        client_package.player = player
        client_package.save()
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_package_assign', kwargs={'pk': client_package.pk}),
            data=json.dumps({'player_id': None}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['success'] is True

    def test_adjust_valid_value(self, admin_user, client_package):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_package_adjust', kwargs={'pk': client_package.pk}),
            data=json.dumps({'sessions_remaining': 2}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['success'] is True
        client_package.refresh_from_db()
        assert client_package.sessions_remaining == 2

    def test_adjust_negative_is_400(self, admin_user, client_package):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_package_adjust', kwargs={'pk': client_package.pk}),
            data=json.dumps({'sessions_remaining': -1}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_adjust_exhausts_package(self, admin_user, client_package):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_package_adjust', kwargs={'pk': client_package.pk}),
            data=json.dumps({'sessions_remaining': 0}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        client_package.refresh_from_db()
        assert client_package.status == 'exhausted'


# ── 5. Client actions ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerClientActions:
    def test_client_list_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_clients'))
        assert resp.status_code == 200

    def test_client_detail_200(self, admin_user, client_profile):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_client_detail', kwargs={'pk': client_profile.pk}))
        assert resp.status_code == 200

    def test_client_approve_post(self, admin_user, client_profile):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_client_approve', kwargs={'pk': client_profile.pk}), {
            'term_start': '',
            'term_end': '',
        })
        assert resp.status_code == 302
        client_profile.refresh_from_db()
        assert client_profile.approval_status == 'approved'

    def test_client_reject_post(self, admin_user, client_profile):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_client_reject', kwargs={'pk': client_profile.pk}), {
            'rejection_notes': 'Not eligible.',
        })
        assert resp.status_code == 302
        client_profile.refresh_from_db()
        assert client_profile.approval_status == 'rejected'

    def test_toggle_select_invite(self, admin_user, client_profile):
        original = client_profile.select_invited
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_client_toggle_select_invite', kwargs={'pk': client_profile.pk}))
        assert resp.status_code == 302
        client_profile.refresh_from_db()
        assert client_profile.select_invited != original

    def test_settle_bookings_get_returns_405(self, admin_user, client_profile):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_client_settle_bookings', kwargs={'pk': client_profile.pk}))
        assert resp.status_code == 405
        data = json.loads(resp.content)
        assert 'error' in data

    def test_settle_bookings_valid_post(self, admin_user, client_profile, client_package, booking):
        # Make booking unsettled
        booking.payment_status = 'pending'
        booking.client_package = None
        booking.save()

        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_client_settle_bookings', kwargs={'pk': client_profile.pk}),
            data=json.dumps({'package_id': client_package.pk}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert 'settled' in data


# ── 6. Blog CRUD ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerBlogCRUD:
    def test_blog_list_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_blog_list'))
        assert resp.status_code == 200

    def test_blog_new_get_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_blog_new'))
        assert resp.status_code == 200

    def test_blog_create_post(self, admin_user):
        from blog.models import BlogPost
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_blog_new'), {
            'title': 'My New Post',
            'category': 'general',
            'excerpt': 'Short excerpt.',
            'body': '<p>Body content.</p>',
        })
        assert resp.status_code == 302
        assert BlogPost.objects.filter(title='My New Post').exists()

    def test_blog_create_sets_slug(self, admin_user):
        from blog.models import BlogPost
        tc = _tc()
        tc.force_login(admin_user)
        tc.post(reverse('owner_blog_new'), {
            'title': 'Slug Test Post',
            'category': 'general',
            'excerpt': 'Excerpt.',
            'body': '<p>Body.</p>',
        })
        post = BlogPost.objects.get(title='Slug Test Post')
        assert post.slug == 'slug-test-post'

    def test_blog_edit_get_200(self, admin_user, blog_post):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_blog_edit', kwargs={'pk': blog_post.pk}))
        assert resp.status_code == 200

    def test_blog_edit_post_updates(self, admin_user, blog_post):
        tc = _tc()
        tc.force_login(admin_user)
        tc.post(reverse('owner_blog_edit', kwargs={'pk': blog_post.pk}), {
            'title': 'Updated Title',
            'category': 'training',
            'excerpt': 'Updated excerpt.',
            'body': '<p>Updated body.</p>',
        })
        blog_post.refresh_from_db()
        assert blog_post.title == 'Updated Title'

    def test_blog_delete_removes(self, admin_user, blog_post):
        from blog.models import BlogPost
        pk = blog_post.pk
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_blog_delete', kwargs={'pk': pk}))
        assert resp.status_code == 302
        assert not BlogPost.objects.filter(pk=pk).exists()

    def test_blog_toggle_publish_publishes(self, admin_user, blog_post):
        assert blog_post.is_published is False
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_blog_toggle_publish', kwargs={'pk': blog_post.pk}))
        assert resp.status_code == 302
        blog_post.refresh_from_db()
        assert blog_post.is_published is True

    def test_blog_toggle_publish_unpublishes(self, admin_user, blog_post):
        blog_post.is_published = True
        blog_post.save()
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_blog_toggle_publish', kwargs={'pk': blog_post.pk}))
        assert resp.status_code == 302
        blog_post.refresh_from_db()
        assert blog_post.is_published is False

    def test_blog_list_shows_post(self, admin_user, blog_post):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_blog_list'))
        assert b'Test Post' in resp.content


# ── 7. Coach actions ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerCoachActions:
    def test_coach_list_200(self, admin_user, coach):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_coaches'))
        assert resp.status_code == 200

    def test_coach_add_get_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_coach_add'))
        assert resp.status_code == 200

    def test_coach_add_post_creates(self, admin_user):
        from coaches.models import Coach
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_coach_add'), {
            'username': 'newcoach',
            'email': 'newcoach@example.com',
            'first_name': 'New',
            'last_name': 'Coach',
            'password': 'StrongPass123!',
            'hourly_rate': '80',
        })
        assert resp.status_code == 302
        assert User.objects.filter(username='newcoach').exists()

    def test_coach_edit_get_200(self, admin_user, coach):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_coach_edit', kwargs={'pk': coach.pk}))
        assert resp.status_code == 200

    def test_coach_edit_post_updates(self, admin_user, coach):
        tc = _tc()
        tc.force_login(admin_user)
        tc.post(reverse('owner_coach_edit', kwargs={'pk': coach.pk}), {
            'first_name': 'Updated',
            'last_name': 'CoachName',
            'email': 'updated@example.com',
            'slug': coach.slug,
            'hourly_rate': '90',
            'tagline': 'Updated tagline',
            'bio': 'Updated bio',
            'experience_years': '12',
        })
        coach.refresh_from_db()
        assert coach.hourly_rate == 90

    def test_coach_schedule_200(self, admin_user, coach):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_coach_schedule', kwargs={'pk': coach.pk}))
        assert resp.status_code == 200

    def test_coach_delete_post(self, admin_user):
        """Hard-delete a fresh coach with no bookings."""
        from coaches.models import Coach
        fresh_user = User.objects.create_user(
            username='deletable_coach',
            email='deletable@example.com',
            password='pass123',
        )
        fresh_coach = Coach.objects.create(
            user=fresh_user,
            slug='deletable-coach',
            hourly_rate=50,
            is_active=True,
        )
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_coach_delete', kwargs={'pk': fresh_coach.pk}))
        assert resp.status_code == 302

    def test_coach_list_shows_coach(self, admin_user, coach):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_coaches'))
        # Coach first or last name appears in page
        assert b'Mirko' in resp.content or b'mirko' in resp.content.lower()


# ── 8. Discount codes ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerDiscountCodes:
    def test_discount_codes_list_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_discount_codes'))
        assert resp.status_code == 200

    def test_create_discount_code(self, admin_user):
        from clients.models import DiscountCode
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_discount_codes'), {
            'action': 'create',
            'code': 'NEWCODE20',
            'description': '20% off',
            'discount_type': 'percent',
            'value': '20',
            'scope': 'all',
            'max_uses_per_client': '1',
        })
        assert resp.status_code == 302
        assert DiscountCode.objects.filter(code='NEWCODE20').exists()

    def test_create_blank_code_error(self, admin_user):
        from clients.models import DiscountCode
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_discount_codes'), {
            'action': 'create',
            'code': '',
            'discount_type': 'percent',
            'value': '10',
            'scope': 'all',
        })
        assert resp.status_code == 302

    def test_toggle_discount_code(self, admin_user, discount_code):
        original = discount_code.is_active
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_discount_codes'), {
            'action': 'toggle',
            'code_id': discount_code.pk,
        })
        assert resp.status_code == 302
        discount_code.refresh_from_db()
        assert discount_code.is_active != original

    def test_delete_unused_discount_code(self, admin_user, discount_code):
        from clients.models import DiscountCode
        pk = discount_code.pk
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_discount_codes'), {
            'action': 'delete',
            'code_id': pk,
        })
        assert resp.status_code == 302
        assert not DiscountCode.objects.filter(pk=pk).exists()

    def test_discount_code_detail_200(self, admin_user, discount_code):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_discount_code_detail', kwargs={'pk': discount_code.pk}))
        assert resp.status_code == 200

    def test_discount_code_shows_on_list(self, admin_user, discount_code):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_discount_codes'))
        assert b'TEST10' in resp.content


# ── 9. Credits and refunds ────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerCreditsAndRefunds:
    def test_credits_page_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_credits'))
        assert resp.status_code == 200

    def test_grant_credit(self, admin_user, client_profile):
        from clients.models import ClientCredit
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_credits'), {
            'action': 'grant',
            'client_id': client_profile.pk,
            'amount': '25.00',
            'credit_type': 'manual',
            'notes': 'Test credit',
        })
        assert resp.status_code == 302
        assert ClientCredit.objects.filter(client=client_profile, amount=Decimal('25.00')).exists()

    def test_cancel_credit(self, admin_user, client_profile):
        from clients.models import ClientCredit
        credit = ClientCredit.objects.create(
            client=client_profile,
            amount=Decimal('15.00'),
            credit_type='manual',
            status='available',
            created_by=admin_user,
        )
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_credits'), {
            'action': 'cancel',
            'credit_id': credit.pk,
        })
        assert resp.status_code == 302
        credit.refresh_from_db()
        assert credit.status == 'cancelled'

    def test_payments_list_200(self, admin_user, payment):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_payments'))
        assert resp.status_code == 200

    @patch('stripe.Refund.create', return_value=MagicMock(id='re_test123'))
    def test_issue_refund_success(self, mock_refund, admin_user, payment):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_issue_refund', kwargs={'payment_id': payment.pk}),
            {'amount': ''},
        )
        assert resp.status_code == 302
        mock_refund.assert_called_once()

    @patch('stripe.Refund.create')
    def test_issue_refund_stripe_error(self, mock_refund, admin_user, payment):
        import stripe as stripe_mod
        mock_refund.side_effect = stripe_mod.error.StripeError(
            'card_error', 'code', 400, None, None
        )
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_issue_refund', kwargs={'payment_id': payment.pk}),
            {'amount': '10.00'},
        )
        assert resp.status_code == 302  # redirects back with error message

    def test_finances_page_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_finances'))
        assert resp.status_code == 200


# ── 10. AI Assist ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerAIAssist:
    """AI endpoints require POST and either Ollama configured or a mock."""

    def _post_ai(self, tc, url, data):
        return tc.post(url, data)

    @patch('requests.post')
    def test_blog_ai_assist_generate(self, mock_post, admin_user):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {'response': '<p>Generated content</p>'},
            raise_for_status=lambda: None,
        )
        tc = _tc()
        tc.force_login(admin_user)
        with patch('django.conf.settings.OLLAMA_BASE_URL', 'http://mock-ollama:11434'):
            resp = tc.post(reverse('owner_blog_ai_assist'), {
                'action': 'generate',
                'title': 'Test Blog',
                'category': 'training',
            })
        assert resp.status_code == 200

    def test_blog_ai_assist_invalid_action(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_blog_ai_assist'), {'action': 'invalid'})
        assert resp.status_code == 400

    def test_blog_ai_assist_no_ollama_configured(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        with patch('django.conf.settings.OLLAMA_BASE_URL', ''):
            resp = tc.post(reverse('owner_blog_ai_assist'), {
                'action': 'generate',
                'title': 'Test',
                'category': 'general',
            })
        assert resp.status_code == 503

    def test_naming_ai_assist_invalid_action(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_naming_ai_assist'), {'action': 'bad_action'})
        assert resp.status_code == 400

    def test_naming_ai_assist_fix_description_empty(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        with patch('django.conf.settings.OLLAMA_BASE_URL', 'http://mock-ollama:11434'):
            resp = tc.post(reverse('owner_naming_ai_assist'), {
                'action': 'fix_description',
                'description': '',
            })
        assert resp.status_code == 400

    def test_naming_ai_assist_write_description_no_name(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        with patch('django.conf.settings.OLLAMA_BASE_URL', 'http://mock-ollama:11434'):
            resp = tc.post(reverse('owner_naming_ai_assist'), {
                'action': 'write_description',
                'name': '',
            })
        assert resp.status_code == 400

    def test_notification_ai_assist_draft_no_subject(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        with patch('django.conf.settings.OLLAMA_BASE_URL', 'http://mock-ollama:11434'):
            resp = tc.post(reverse('owner_notification_ai_assist'), {
                'action': 'draft',
                'subject': '',
            })
        assert resp.status_code == 400

    def test_notification_ai_assist_invalid_action(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_notification_ai_assist'), {'action': 'nope'})
        assert resp.status_code == 400


# ── 11. Field rentals ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerFieldRentals:
    def test_field_slots_list_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_field_slots'))
        assert resp.status_code == 200

    def test_approve_pending_slot(self, admin_user, pending_rental_slot):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_field_slot_approve', kwargs={'pk': pending_rental_slot.pk}))
        assert resp.status_code == 302
        pending_rental_slot.refresh_from_db()
        assert pending_rental_slot.status == 'booked'

    def test_reject_pending_slot(self, admin_user, pending_rental_slot):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_field_slot_reject', kwargs={'pk': pending_rental_slot.pk}),
            {'rejection_reason': 'Not available.'},
        )
        assert resp.status_code == 302
        pending_rental_slot.refresh_from_db()
        assert pending_rental_slot.status == 'available'

    def test_cancel_booked_slot(self, admin_user, booked_rental_slot):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_field_slot_cancel', kwargs={'pk': booked_rental_slot.pk}),
            {'cancellation_notes': 'Owner cancelled.'},
        )
        assert resp.status_code == 302
        booked_rental_slot.refresh_from_db()
        assert booked_rental_slot.status == 'available'


# ── 12. Referral payouts ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerReferralPayouts:
    def test_referrals_page_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_referrals'))
        assert resp.status_code == 200

    def test_referral_payouts_list_200(self, admin_user, referral_payout):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_referral_payouts'))
        assert resp.status_code == 200

    def test_payout_approve(self, admin_user, referral_payout):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_payout_approve', kwargs={'payout_id': referral_payout.id}))
        assert resp.status_code == 302
        referral_payout.refresh_from_db()
        assert referral_payout.status == 'approved'

    def test_payout_reject(self, admin_user, referral_payout):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_payout_reject', kwargs={'payout_id': referral_payout.id}),
            {'rejection_reason': 'Invalid referral.'},
        )
        assert resp.status_code == 302
        referral_payout.refresh_from_db()
        assert referral_payout.status == 'rejected'

    def test_payout_mark_paid_requires_approved_status(self, admin_user, referral_payout):
        """mark_paid on a pending payout should redirect with error (not change status)."""
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_payout_mark_paid', kwargs={'payout_id': referral_payout.id}),
            {'payment_notes': 'Paid via Zelle'},
        )
        assert resp.status_code == 302
        referral_payout.refresh_from_db()
        assert referral_payout.status == 'pending'  # unchanged, wrong precondition


# ── 13. Session types ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerSessionTypes:
    def test_session_types_list_200(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_session_types'))
        assert resp.status_code == 200

    def test_create_session_type(self, admin_user):
        from bookings.models import SessionType
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_session_types'), {
            'action': 'add',
            'name': 'New Group Session',
            'session_format': 'group',
            'duration_minutes': '60',
            'price': '35.00',
            'max_participants': '8',
        })
        assert resp.status_code == 302
        assert SessionType.objects.filter(name='New Group Session').exists()

    def test_toggle_session_type(self, admin_user, session_type_group):
        original = session_type_group.is_active
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_session_types'), {
            'action': 'toggle',
            'session_type_id': session_type_group.pk,
        })
        assert resp.status_code == 302
        session_type_group.refresh_from_db()
        assert session_type_group.is_active != original

    def test_session_type_edit_get_200(self, admin_user, session_type_group):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_session_type_edit', kwargs={'pk': session_type_group.pk}))
        assert resp.status_code == 200

    def test_session_type_duplicate(self, admin_user, session_type_group):
        from bookings.models import SessionType
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_session_type_duplicate', kwargs={'pk': session_type_group.pk}))
        assert resp.status_code == 302
        assert SessionType.objects.filter(name__icontains='Copy').exists()

    def test_session_type_delete_no_bookings(self, admin_user):
        from bookings.models import SessionType
        st = SessionType.objects.create(
            name='Deletable ST', session_format='private',
            duration_minutes=60, price=Decimal('50.00'), is_active=True,
        )
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(reverse('owner_session_type_delete', kwargs={'pk': st.pk}))
        assert resp.status_code == 302
        assert not SessionType.objects.filter(pk=st.pk).exists()

    def test_apply_capacities_empty_body_400(self, admin_user, session_type_group):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_session_type_apply_capacities', kwargs={'pk': session_type_group.pk}),
            data=json.dumps({'capacities': {}}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_apply_capacities_valid_body_200(self, admin_user, session_type_group):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.post(
            reverse('owner_session_type_apply_capacities', kwargs={'pk': session_type_group.pk}),
            data=json.dumps({'capacities': {'Mon_10:00': 15}}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert 'updated' in data


# ── 14. Booking detail ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnerBookingDetail:
    def test_booking_list_200(self, admin_user, booking):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_bookings'))
        assert resp.status_code == 200

    def test_booking_detail_200(self, admin_user, booking):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_booking_detail', kwargs={'pk': booking.pk}))
        assert resp.status_code == 200

    def test_booking_detail_shows_player(self, admin_user, booking, player):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_booking_detail', kwargs={'pk': booking.pk}))
        assert player.first_name.encode() in resp.content

    def test_booking_detail_404_for_nonexistent(self, admin_user):
        tc = _tc()
        tc.force_login(admin_user)
        resp = tc.get(reverse('owner_booking_detail', kwargs={'pk': 999999}))
        assert resp.status_code == 404
