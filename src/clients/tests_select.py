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


# ===========================================================================
# F. Email notification tests
# ===========================================================================

@pytest.mark.django_db
def test_publish_game_sends_email_when_enabled(settings, mailoutbox):
    """Email is sent to each new RSVP recipient when PRODUCTION_EMAIL_ENABLED=True."""
    settings.PRODUCTION_EMAIL_ENABLED = True

    mgr_user = _make_user('email_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, slug='email-team')

    member_user = _make_user('email_member')
    member_client = _make_client_obj(member_user)
    pkg = _make_select_package()
    player = _make_player(member_client, team=team)
    _make_active_client_package(member_client, pkg, player=player)

    game = _make_select_game(team, created_by=mgr_user, status='draft')
    game.status = 'published'
    game.save()

    assert len(mailoutbox) == 1
    mail = mailoutbox[0]
    assert member_user.email in mail.to
    assert 'APC Select Game' in mail.subject
    assert team.name in mail.subject or team.name in mail.body


@pytest.mark.django_db
def test_publish_game_no_email_when_disabled(settings, mailoutbox):
    """No email is sent when PRODUCTION_EMAIL_ENABLED=False (default in tests)."""
    settings.PRODUCTION_EMAIL_ENABLED = False

    mgr_user = _make_user('noemail_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, slug='noemail-team')

    member_user = _make_user('noemail_member')
    member_client = _make_client_obj(member_user)
    pkg = _make_select_package()
    player = _make_player(member_client, team=team)
    _make_active_client_package(member_client, pkg, player=player)

    game = _make_select_game(team, created_by=mgr_user, status='draft')
    game.status = 'published'
    game.save()

    assert len(mailoutbox) == 0


@pytest.mark.django_db
def test_publish_game_email_idempotent_no_duplicate_emails(settings, mailoutbox):
    """Re-saving a published game does not send additional emails."""
    settings.PRODUCTION_EMAIL_ENABLED = True

    mgr_user = _make_user('idem_email_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, slug='idem-email-team')

    member_user = _make_user('idem_email_member')
    member_client = _make_client_obj(member_user)
    pkg = _make_select_package()
    player = _make_player(member_client, team=team)
    _make_active_client_package(member_client, pkg, player=player)

    game = _make_select_game(team, created_by=mgr_user, status='draft')
    game.status = 'published'
    game.save()

    first_count = len(mailoutbox)

    # Re-save (e.g. owner edits notes)
    game.notes = 'Updated location details'
    game.save()

    assert len(mailoutbox) == first_count  # no new emails


@pytest.mark.django_db
def test_publish_game_email_contains_date_and_location(settings, mailoutbox):
    """Email body contains the game date and location."""
    settings.PRODUCTION_EMAIL_ENABLED = True

    mgr_user = _make_user('content_mgr')
    mgr_client = _make_client_obj(mgr_user)
    team = _make_select_team(mgr_client, slug='content-team')

    member_user = _make_user('content_member')
    member_client = _make_client_obj(member_user)
    pkg = _make_select_package()
    player = _make_player(member_client, team=team)
    _make_active_client_package(member_client, pkg, player=player)

    game = _make_select_game(team, created_by=mgr_user, status='draft')
    game.status = 'published'
    game.save()

    assert len(mailoutbox) == 1
    mail = mailoutbox[0]
    assert 'APC Field 1' in mail.body


# ===========================================================================
# F. Owner team roster management tests
# ===========================================================================

def _make_owner_user(username='troster_owner'):
    user = _make_user(username)
    user.is_staff = True
    user.save()
    return user


@pytest.mark.django_db
def test_owner_team_detail_renders_primary_roster():
    """Team detail page shows primary roster players."""
    owner = _make_owner_user('tdr_owner')
    mgr_client = _make_client_obj(owner)
    team = _make_select_team(mgr_client, slug='tdr-team')
    player = _make_player(mgr_client, team=team, first='Jamie', last='Roster')

    tc = TestClient()
    tc.force_login(owner)
    url = reverse('owner_team_detail', kwargs={'pk': team.pk})
    resp = tc.get(url)
    assert resp.status_code == 200
    assert b'Jamie' in resp.content
    assert b'Roster' in resp.content


@pytest.mark.django_db
def test_owner_team_assign_primary_sets_team():
    """POST assign_primary sets player.team to this team."""
    owner = _make_owner_user('tap_owner')
    mgr_client = _make_client_obj(owner)
    team = _make_select_team(mgr_client, slug='tap-team')
    player = _make_player(mgr_client, team=None, first='Sam', last='Primary')

    tc = TestClient()
    tc.force_login(owner)
    url = reverse('owner_team_detail', kwargs={'pk': team.pk})
    resp = tc.post(url, {'action': 'assign_primary', 'player_id': str(player.pk)})
    assert resp.status_code == 302
    player.refresh_from_db()
    assert player.team_id == team.pk


@pytest.mark.django_db
def test_owner_team_remove_primary_clears_team():
    """POST remove_primary sets player.team to None."""
    owner = _make_owner_user('trp_owner')
    mgr_client = _make_client_obj(owner)
    team = _make_select_team(mgr_client, slug='trp-team')
    player = _make_player(mgr_client, team=team, first='Pat', last='Primary')

    tc = TestClient()
    tc.force_login(owner)
    url = reverse('owner_team_detail', kwargs={'pk': team.pk})
    resp = tc.post(url, {'action': 'remove_primary', 'player_id': str(player.pk)})
    assert resp.status_code == 302
    player.refresh_from_db()
    assert player.team_id is None


@pytest.mark.django_db
def test_owner_team_add_guest_callup():
    """POST add_guest adds player to select_teams M2M."""
    owner = _make_owner_user('tag_owner')
    mgr_client = _make_client_obj(owner)
    team = _make_select_team(mgr_client, slug='tag-team')

    other_user = _make_user('tag_other')
    other_client = _make_client_obj(other_user)
    player = _make_player(other_client, team=None, first='Riley', last='Guest')

    tc = TestClient()
    tc.force_login(owner)
    url = reverse('owner_team_detail', kwargs={'pk': team.pk})
    resp = tc.post(url, {'action': 'add_guest', 'player_id': str(player.pk)})
    assert resp.status_code == 302
    assert team in player.select_teams.all()


@pytest.mark.django_db
def test_owner_team_remove_guest_callup():
    """POST remove_guest removes player from select_teams M2M."""
    owner = _make_owner_user('trg_owner')
    mgr_client = _make_client_obj(owner)
    team = _make_select_team(mgr_client, slug='trg-team')

    other_user = _make_user('trg_other')
    other_client = _make_client_obj(other_user)
    player = _make_player(other_client, team=None, first='Casey', last='Guest')
    player.select_teams.add(team)

    tc = TestClient()
    tc.force_login(owner)
    url = reverse('owner_team_detail', kwargs={'pk': team.pk})
    resp = tc.post(url, {'action': 'remove_guest', 'player_id': str(player.pk)})
    assert resp.status_code == 302
    assert team not in player.select_teams.all()


@pytest.mark.django_db
def test_owner_team_detail_shows_guest_section_for_select_team():
    """Guest callups section is visible on Select team detail page."""
    owner = _make_owner_user('tgs_owner')
    mgr_client = _make_client_obj(owner)
    team = _make_select_team(mgr_client, slug='tgs-team')

    tc = TestClient()
    tc.force_login(owner)
    url = reverse('owner_team_detail', kwargs={'pk': team.pk})
    resp = tc.get(url)
    assert resp.status_code == 200
    assert b'Guest Callup' in resp.content


@pytest.mark.django_db
def test_owner_team_detail_available_players_excludes_roster():
    """Players already on the team do not appear in the add modal player list."""
    owner = _make_owner_user('tae_owner')
    mgr_client = _make_client_obj(owner)
    team = _make_select_team(mgr_client, slug='tae-team')
    player_on = _make_player(mgr_client, team=team, first='On', last='Roster')

    other_user = _make_user('tae_other')
    other_client = _make_client_obj(other_user)
    player_off = _make_player(other_client, team=None, first='Off', last='Roster')

    tc = TestClient()
    tc.force_login(owner)
    url = reverse('owner_team_detail', kwargs={'pk': team.pk})
    resp = tc.get(url)
    assert resp.status_code == 200
    available = list(resp.context['available_players'])
    ids = [p.pk for p in available]
    assert player_on.pk not in ids
    assert player_off.pk in ids


# ---------------------------------------------------------------------------
# Select game creation — regression for date/time strings never being
# parsed before SelectGame.objects.create(), which crashed the post_save
# RSVP-fanout signal's instance.date.strftime() call (reported by Mirko).
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_owner_create_select_game_parses_date_and_time():
    """POSTed date/time strings (from <input type=date/time>) must become
    real date/time objects — not raw strings — before the game is saved."""
    from bookings.models import SelectGame

    owner = _make_owner_user('ocg_owner')
    mgr_client = _make_client_obj(owner)
    team = _make_select_team(mgr_client, slug='ocg-team')

    tc = TestClient()
    tc.force_login(owner)
    resp = tc.post(reverse('owner_select_games'), {
        'action': 'create',
        'team_id': str(team.pk),
        'date': '2026-08-09',
        'start_time': '10:00',
        'end_time': '11:30',
        'location': 'Hocker Grove Middle',
        'publish': '1',
    })
    assert resp.status_code == 302

    game = SelectGame.objects.get(team=team)
    assert game.date == date(2026, 8, 9)
    assert game.start_time == time(10, 0)
    assert game.end_time == time(11, 30)
    assert game.status == 'published'


@pytest.mark.django_db
def test_coach_create_select_game_parses_date_and_time():
    """Same regression, via the coach-portal create-game form."""
    from bookings.models import SelectGame
    from coaches.models import Coach

    from django.contrib.auth.models import Group
    coach_user = _make_user('ccg_coach')
    coach_user.groups.add(Group.objects.get_or_create(name='Coach')[0])
    coach = Coach.objects.create(user=coach_user, slug='ccg-coach')
    mgr_client = _make_client_obj(_make_owner_user('ccg_owner'))
    team = _make_select_team(mgr_client, slug='ccg-team')

    tc = TestClient()
    tc.force_login(coach_user)
    resp = tc.post(reverse('coaches:select_games'), {
        'action': 'create',
        'team_id': str(team.pk),
        'date': '2026-08-09',
        'start_time': '10:00',
        'end_time': '',
        'location': 'Hocker Grove Middle',
        'publish': '0',
    })
    assert resp.status_code == 302

    game = SelectGame.objects.get(team=team)
    assert game.date == date(2026, 8, 9)
    assert game.start_time == time(10, 0)
    assert game.end_time is None
    assert game.status == 'draft'
