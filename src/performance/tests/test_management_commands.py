"""
Tests for performance management commands.
"""
import pytest
from io import StringIO
from unittest.mock import patch
from django.core.management import call_command

from clients.models import Client, Player
from performance.models import ValdProfile


pytestmark = pytest.mark.django_db


def _profile(profile_id, given, family, birth_year=2015):
    return {
        'profileId': profile_id,
        'givenName': given,
        'familyName': family,
        'dateOfBirth': f'{birth_year}-03-20T00:00:00',
    }


@pytest.fixture
def make_player(django_user_model):
    def _make(username, first_name, last_name, birth_year=2015):
        user = django_user_model.objects.create_user(
            username=username, email=username, password='testpass123',
        )
        client = Client.objects.create(user=user, phone='555-0000')
        return Player.objects.create(
            client=client, first_name=first_name, last_name=last_name,
            birth_year=birth_year, is_active=True,
        )
    return _make


class TestValdMatchProfiles:
    """Test vald_match_profiles auto-matching and duplicate-profile handling."""

    @patch('performance.management.commands.vald_match_profiles.list_profiles')
    def test_unique_match_creates_link(self, mock_list, make_player):
        player = make_player('parent1@example.com', 'Rylan', 'Turner', 2013)
        mock_list.return_value = [_profile('p1', 'Rylan', 'Turner', 2013)]

        call_command('vald_match_profiles', stdout=StringIO())

        profile = ValdProfile.objects.get(player=player)
        assert profile.vald_profile_id == 'p1'
        assert profile.match_method == 'auto_name_dob'

    @patch('performance.management.commands.vald_match_profiles.list_profiles')
    def test_duplicate_vald_profiles_for_same_player_does_not_crash(self, mock_list, make_player):
        """Two VALD profileIds, same name+DOB — a real Hub data-entry duplicate
        seen in production. Must not attempt to link the same Player twice."""
        player = make_player('parent2@example.com', 'Ian', 'Johnson', 2015)
        mock_list.return_value = [
            _profile('dup-1', 'Ian', 'Johnson', 2015),
            _profile('dup-2', 'Ian', 'Johnson', 2015),
        ]

        out = StringIO()
        call_command('vald_match_profiles', stdout=out)

        assert ValdProfile.objects.filter(player=player).count() == 1
        assert 'DUPLICATE VALD PROFILES' in out.getvalue()

    @patch('performance.management.commands.vald_match_profiles.list_profiles')
    def test_ambiguous_roster_duplicates_not_matched(self, mock_list, make_player):
        """Two Players share name+DOB — must not guess which one to link."""
        make_player('parent3@example.com', 'Ryan', 'Rivera', 2010)
        make_player('parent4@example.com', 'Ryan', 'Rivera', 2010)
        mock_list.return_value = [_profile('p1', 'Ryan', 'Rivera', 2010)]

        out = StringIO()
        call_command('vald_match_profiles', stdout=out)

        assert ValdProfile.objects.count() == 0
        assert 'AMBIGUOUS' in out.getvalue()

    @patch('performance.management.commands.vald_match_profiles.list_profiles')
    def test_dry_run_creates_nothing(self, mock_list, make_player):
        make_player('parent5@example.com', 'Rylan', 'Turner', 2013)
        mock_list.return_value = [_profile('p1', 'Rylan', 'Turner', 2013)]

        call_command('vald_match_profiles', '--dry-run', stdout=StringIO())

        assert ValdProfile.objects.count() == 0
