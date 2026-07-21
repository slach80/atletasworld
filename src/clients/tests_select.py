"""
Tests for APC Select features:
  A. Model tests
  B. Signal (fanout) tests
  C. Utility tests
  D. Billing tier / renewal tests
  E. HTTP smoke tests
"""
import pytest
from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import Client as TestClient
from django.urls import reverse
from django.utils import timezone


# ---------------------------------------------------------------------------
# Local helpers — create minimal objects without pulling in all fixtures
# ---------------------------------------------------------------------------

def _make_user(username, password='pass1234'):
    return User.objects.create_user(username=username, email=f'{username}@test.com', password=password)


def _make_client_obj(user):
    from clients.models import Client
    return Client.objects.create(
        user=user,
        client_type='parent',
        phone='555-0000',
        address='1 Test St',
        emergency_contact='EC',
        emergency_phone='555-0001',
    )


def _make_select_team(manager_client, name='APC Select 2014', slug=None):
    from clients.models import Team
    return Team.objects.create(
        name=name,
        slug=slug or name.lower().replace(' ', '-'),
        age_group='U12',
        manager=manager_client,
        is_select=True,
        is_active=True,
    )


def _make_non_select_team(manager_client, name='Regular Team', slug=None):
    from clients.models import Team
    return Team.objects.create(
        name=name,
        slug=slug or name.lower().replace(' ', '-'),
        age_group='U12',
        manager=manager_client,
        is_select=False,
        is_active=True,
    )


def _make_player(client_obj, team=None, first='Alex', last='Player'):
    from clients.models import Player
    return Player.objects.create(
        client=client_obj,
        team=team,
        first_name=first,
        last_name=last,
        birth_year=2012,
        gender='M',
        is_active=True,
    )


def _make_select_package():
    from clients.models import Package
    return Package.objects.create(
        name='APC Select Monthly',
        package_type='select',
        price='99.00',
        sessions_included=0,
        validity_weeks=4,
        billing_tier='monthly',
        is_active=True,
    )


def _make_active_client_package(client_obj, package, player=None):
    from clients.models import ClientPackage
    today = timezone.localdate()
    return ClientPackage.objects.create(
        client=client_obj,
        package=package,
        player=player,
        start_date=today,
        expiry_date=today + timedelta(weeks=4),
        sessions_remaining=0,
        sessions_used=0,
        status='active',
    )


def _make_select_game(team, created_by, status='draft'):
    from bookings.models import SelectGame
    return SelectGame.objects.create(
        team=team,
        created_by=created_by,
        date=date.today() + timedelta(days=7),
        start_time=time(10, 0),
        location='APC Field 1',
        status=status,
    )


# ===========================================================================
# A. Model tests
# ===========================================================================

@pytest.mark.django_db
def test_team_is_select_defaults_false():
    user = _make_user('team_mgr')
    client_obj = _make_client_obj(user)
    from clients.models import Team
    team = Team.objects.create(
        name='Plain Team',
        slug='plain-team',
        age_group='U10',
        manager=client_obj,
    )
    assert team.is_select is False


@pytest.mark.django_db
def test_team_is_select_can_be_true():
    user = _make_user('select_mgr')
    client_obj = _make_client_obj(user)
    team = _make_select_team(client_obj)
    assert team.is_select is True


@pytest.mark.django_db
def test_player_select_teams_m2m():
    user = _make_user('m2m_user')
    client_obj = _make_client_obj(user)
    mgr_user = _make_user('m2m_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, name='APC Select 2015', slug='apc-select-2015')
    player = _make_player(client_obj)

    player.select_teams.add(team)
    assert team in player.select_teams.all()


@pytest.mark.django_db
def test_package_billing_tier_field_exists_and_choices_valid():
    from clients.models import Package
    pkg = Package.objects.create(
        name='APC Select Thirds',
        package_type='select',
        price='299.00',
        sessions_included=0,
        validity_weeks=16,
        billing_tier='thirds',
        is_active=True,
    )
    # field persists
    assert pkg.billing_tier == 'thirds'
    # choice is in the declared choices
    valid_keys = [c[0] for c in Package.BILLING_TIER_CHOICES]
    assert 'thirds' in valid_keys
    assert 'monthly' in valid_keys
    assert 'half' in valid_keys
    assert 'full' in valid_keys


@pytest.mark.django_db
def test_select_game_creates_with_draft_status_and_str():
    user = _make_user('sg_owner')
    client_obj = _make_client_obj(user)
    team = _make_select_team(client_obj, slug='sg-team')
    game = _make_select_game(team, created_by=user, status='draft')

    assert game.status == 'draft'
    assert game.pk is not None
    assert 'sg-team' in str(game).lower() or team.name in str(game)


@pytest.mark.django_db
def test_select_game_rsvp_unique_together_raises():
    from bookings.models import SelectGameRSVP

    user = _make_user('rsvp_owner')
    client_obj = _make_client_obj(user)
    team = _make_select_team(client_obj, slug='rsvp-team')
    game = _make_select_game(team, created_by=user, status='published')

    client_user = _make_user('rsvp_client')
    rsvp_client = _make_client_obj(client_user)

    SelectGameRSVP.objects.create(game=game, client=rsvp_client, status='pending')

    with pytest.raises(IntegrityError):
        SelectGameRSVP.objects.create(game=game, client=rsvp_client, status='coming')


# ===========================================================================
# B. Signal tests
# ===========================================================================

@pytest.mark.django_db
def test_publish_game_fans_out_rsvps_to_select_members():
    from bookings.models import SelectGameRSVP

    mgr_user = _make_user('fanout_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, slug='fanout-team')

    member_user = _make_user('fanout_member')
    member_client = _make_client_obj(member_user)
    pkg = _make_select_package()
    player = _make_player(member_client, team=team)
    _make_active_client_package(member_client, pkg, player=player)

    game = _make_select_game(team, created_by=mgr_user, status='draft')
    assert SelectGameRSVP.objects.filter(game=game, client=member_client).count() == 0

    game.status = 'published'
    game.save()

    assert SelectGameRSVP.objects.filter(game=game, client=member_client).count() == 1


@pytest.mark.django_db
def test_publish_game_idempotent_no_duplicate_rsvps():
    from bookings.models import SelectGameRSVP

    mgr_user = _make_user('idem_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, slug='idem-team')

    member_user = _make_user('idem_member')
    member_client = _make_client_obj(member_user)
    pkg = _make_select_package()
    player = _make_player(member_client, team=team)
    _make_active_client_package(member_client, pkg, player=player)

    game = _make_select_game(team, created_by=mgr_user, status='draft')
    game.status = 'published'
    game.save()

    # Re-save a published game — must not double the RSVPs
    game.notes = 'Updated notes'
    game.save()

    assert SelectGameRSVP.objects.filter(game=game, client=member_client).count() == 1


@pytest.mark.django_db
def test_publish_game_does_not_fanout_to_other_team_member():
    from bookings.models import SelectGameRSVP

    mgr_user = _make_user('other_mgr')
    mgr_client = _make_client_obj(mgr_user)

    team_a = _make_select_team(mgr_client, name='Select Team A', slug='select-team-a')
    team_b = _make_select_team(mgr_client, name='Select Team B', slug='select-team-b')

    other_user = _make_user('other_member')
    other_client = _make_client_obj(other_user)
    pkg = _make_select_package()
    player = _make_player(other_client, team=team_b)
    _make_active_client_package(other_client, pkg, player=player)

    # Game is for team_a; member is on team_b — should NOT get an RSVP
    game = _make_select_game(team_a, created_by=mgr_user, status='draft')
    game.status = 'published'
    game.save()

    assert SelectGameRSVP.objects.filter(game=game, client=other_client).count() == 0


@pytest.mark.django_db
def test_guest_invitee_gets_rsvp_on_publish():
    from bookings.models import SelectGameRSVP

    mgr_user = _make_user('guest_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, slug='guest-team')

    guest_user = _make_user('guest_invitee')
    guest_client = _make_client_obj(guest_user)

    game = _make_select_game(team, created_by=mgr_user, status='draft')
    game.guest_invitees.add(guest_client)

    game.status = 'published'
    game.save()

    assert SelectGameRSVP.objects.filter(game=game, client=guest_client).count() == 1


# ===========================================================================
# C. Utility tests
# ===========================================================================

@pytest.mark.django_db
def test_get_player_select_team_ids_returns_select_team():
    from bookings.utils import get_player_select_team_ids

    user = _make_user('util_select')
    client_obj = _make_client_obj(user)
    mgr = _make_client_obj(_make_user('util_mgr'))
    team = _make_select_team(mgr, slug='util-select-team')
    _make_player(client_obj, team=team)

    ids = get_player_select_team_ids(user)
    assert team.pk in ids


@pytest.mark.django_db
def test_get_player_select_team_ids_empty_for_non_select_team():
    from bookings.utils import get_player_select_team_ids

    user = _make_user('util_nonselect')
    client_obj = _make_client_obj(user)
    mgr = _make_client_obj(_make_user('util_mgr2'))
    team = _make_non_select_team(mgr, slug='util-regular-team')
    _make_player(client_obj, team=team)

    ids = get_player_select_team_ids(user)
    assert ids == []


@pytest.mark.django_db
def test_get_player_select_team_ids_empty_for_anonymous():
    from bookings.utils import get_player_select_team_ids
    from django.contrib.auth.models import AnonymousUser

    assert get_player_select_team_ids(AnonymousUser()) == []


# ===========================================================================
# D. Billing tier / renewal tests
# ===========================================================================

@pytest.mark.django_db
def test_billing_tier_weeks_has_expected_tiers():
    from payments.views import _BILLING_TIER_WEEKS

    assert _BILLING_TIER_WEEKS == {
        'monthly': 4,
        'thirds':  16,
        'half':    12,
        'full':    52,
    }


@pytest.mark.django_db
def test_handle_subscription_renewed_extends_expiry_by_16_weeks_for_thirds():
    from payments.views import _handle_subscription_renewed
    from clients.models import ClientPackage, Package
    from datetime import timedelta

    user = _make_user('renewal_user')
    client_obj = _make_client_obj(user)
    pkg = Package.objects.create(
        name='APC Select Thirds',
        package_type='select',
        price='299.00',
        sessions_included=0,
        validity_weeks=16,
        billing_tier='thirds',
        is_active=True,
    )
    today = timezone.localdate()
    cp = ClientPackage.objects.create(
        client=client_obj,
        package=pkg,
        start_date=today,
        expiry_date=today + timedelta(weeks=4),   # starts with less time
        sessions_remaining=0,
        sessions_used=0,
        status='active',
        stripe_subscription_id='sub_test_thirds_001',
    )

    fake_invoice = {'subscription': 'sub_test_thirds_001'}
    _handle_subscription_renewed(fake_invoice)

    cp.refresh_from_db()
    expected = today + timedelta(weeks=16)
    assert cp.expiry_date == expected


# ===========================================================================
# E. HTTP smoke tests
# ===========================================================================

@pytest.mark.django_db
def test_rsvp_get_returns_405():
    user = _make_user('get405_user')
    client_obj = _make_client_obj(user)
    mgr = _make_client_obj(_make_user('get405_mgr'))
    team = _make_select_team(mgr, slug='get405-team')
    game = _make_select_game(team, created_by=mgr.user, status='published')

    tc = TestClient()
    tc.force_login(user)
    url = reverse('clients:select_game_rsvp', kwargs={'game_id': game.pk})
    response = tc.get(url)
    assert response.status_code == 405


@pytest.mark.django_db
def test_rsvp_unauthenticated_redirects():
    mgr_user = _make_user('anon_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, slug='anon-team')
    game = _make_select_game(team, created_by=mgr_user, status='published')

    tc = TestClient()
    url = reverse('clients:select_game_rsvp', kwargs={'game_id': game.pk})
    response = tc.post(url, {'status': 'coming'})
    assert response.status_code == 302
    assert '/login' in response['Location'] or '/accounts' in response['Location']


@pytest.mark.django_db
def test_rsvp_client_with_rsvp_can_update_status():
    from bookings.models import SelectGameRSVP

    mgr_user = _make_user('rsvp_update_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, slug='rsvp-update-team')
    game = _make_select_game(team, created_by=mgr_user, status='published')

    member_user = _make_user('rsvp_update_member')
    member_client = _make_client_obj(member_user)
    SelectGameRSVP.objects.create(game=game, client=member_client, status='pending')

    tc = TestClient()
    tc.force_login(member_user)
    url = reverse('clients:select_game_rsvp', kwargs={'game_id': game.pk})
    response = tc.post(url, {'status': 'coming'})

    assert response.status_code == 200
    import json
    data = json.loads(response.content)
    assert data['ok'] is True
    assert data['status'] == 'coming'


@pytest.mark.django_db
def test_rsvp_client_without_rsvp_gets_403():
    mgr_user = _make_user('no_rsvp_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, slug='no-rsvp-team')
    game = _make_select_game(team, created_by=mgr_user, status='published')

    uninvited_user = _make_user('no_rsvp_member')
    _make_client_obj(uninvited_user)

    tc = TestClient()
    tc.force_login(uninvited_user)
    url = reverse('clients:select_game_rsvp', kwargs={'game_id': game.pk})
    response = tc.post(url, {'status': 'coming'})
    assert response.status_code == 403
