"""
Tests for performance.models.
"""
import pytest
from django.utils import timezone
from datetime import timedelta, timezone as dt_timezone

from clients.models import Client, Player
from performance.models import ValdProfile, ValdTestResult, ValdResultDefinition, ValdSyncRun


pytestmark = pytest.mark.django_db


class TestValdProfile:
    """Test ValdProfile model."""

    def test_create_vald_profile(self, client_user, player):
        """Create a ValdProfile linked to a Player."""
        profile = ValdProfile.objects.create(
            player=player,
            vald_profile_id='vald-123',
            vald_tenant_id='tenant-abc',
            match_method='manual',
        )

        assert profile.player == player
        assert profile.vald_profile_id == 'vald-123'
        assert profile.is_active is True
        assert str(profile) == f"{player.first_name} {player.last_name} → VALD vald-123"

    def test_one_to_one_constraint(self, player):
        """A Player can have only one ValdProfile."""
        ValdProfile.objects.create(
            player=player,
            vald_profile_id='vald-123',
            vald_tenant_id='tenant-abc',
        )

        with pytest.raises(Exception):  # IntegrityError
            ValdProfile.objects.create(
                player=player,
                vald_profile_id='vald-456',
                vald_tenant_id='tenant-abc',
            )


class TestValdResultDefinition:
    """Test ValdResultDefinition model."""

    def test_create_result_definition(self):
        """Create a metric definition."""
        defn = ValdResultDefinition.objects.create(
            result_id='CMJ_JumpHeight',
            system='forcedecks',
            name='Jump Height',
            unit='cm',
            trend_direction='increasing',
            display_order=1,
            show_in_client_portal=True,
        )

        assert defn.result_id == 'CMJ_JumpHeight'
        assert defn.trend_direction == 'increasing'
        assert str(defn) == "Jump Height (forcedecks)"


class TestValdTestResult:
    """Test ValdTestResult model."""

    def test_create_test_result(self, vald_profile):
        """Create a test result."""
        test_date = timezone.now() - timedelta(days=7)

        result = ValdTestResult.objects.create(
            vald_test_id='test-789',
            profile=vald_profile,
            system='forcedecks',
            test_type='CMJ',
            test_date=test_date,
            raw_payload={'foo': 'bar'},
            metrics={'CMJ_JumpHeight': 32.5},
            week_key='2026-W30',
        )

        assert result.vald_test_id == 'test-789'
        assert result.profile == vald_profile
        assert result.metrics['CMJ_JumpHeight'] == 32.5
        assert result.week_key == '2026-W30'

    def test_iso_week_property(self, vald_profile):
        """Derive ISO week from test_date."""
        test_date = timezone.datetime(2026, 7, 27, 10, 0, tzinfo=dt_timezone.utc)

        result = ValdTestResult.objects.create(
            vald_test_id='test-iso',
            profile=vald_profile,
            system='forcedecks',
            test_type='CMJ',
            test_date=test_date,
            raw_payload={},
            metrics={},
            week_key='2026-W31',
        )

        assert result.iso_week == '2026-W31'

    def test_unique_vald_test_id(self, vald_profile):
        """vald_test_id must be unique (idempotency)."""
        ValdTestResult.objects.create(
            vald_test_id='test-unique',
            profile=vald_profile,
            system='forcedecks',
            test_type='CMJ',
            test_date=timezone.now(),
            raw_payload={},
            metrics={},
            week_key='2026-W31',
        )

        with pytest.raises(Exception):  # IntegrityError
            ValdTestResult.objects.create(
                vald_test_id='test-unique',  # duplicate
                profile=vald_profile,
                system='forcedecks',
                test_type='CMJ',
                test_date=timezone.now(),
                raw_payload={},
                metrics={},
                week_key='2026-W31',
            )


class TestValdSyncRun:
    """Test ValdSyncRun model."""

    def test_create_sync_run(self):
        """Create a sync run."""
        run = ValdSyncRun.objects.create(system='forcedecks')
        assert run.status == 'running'
        assert run.records_synced == 0

    def test_finish_ok(self):
        """Mark a sync run as successful."""
        run = ValdSyncRun.objects.create(system='forcedecks')
        last_synced = timezone.now()

        run.finish_ok(records_synced=5, last_synced_at=last_synced)

        run.refresh_from_db()
        assert run.status == 'ok'
        assert run.records_synced == 5
        assert run.last_synced_at == last_synced
        assert run.finished_at is not None

    def test_finish_error(self):
        """Mark a sync run as failed."""
        run = ValdSyncRun.objects.create(system='forcedecks')

        run.finish_error('API timeout')

        run.refresh_from_db()
        assert run.status == 'error'
        assert run.error == 'API timeout'
        assert run.finished_at is not None

    def test_cursor_first_sync(self):
        """Cursor returns far-past date for first sync."""
        cursor = ValdSyncRun.cursor('forcedecks')
        assert cursor == '2000-01-01T00:00:00.000Z'

    def test_cursor_incremental_sync(self):
        """Cursor returns last_synced_at from latest OK run."""
        last_synced = timezone.datetime(2026, 7, 20, 12, 0, 0, tzinfo=dt_timezone.utc)

        run = ValdSyncRun.objects.create(system='forcedecks')
        run.finish_ok(records_synced=3, last_synced_at=last_synced)

        cursor = ValdSyncRun.cursor('forcedecks')
        assert cursor == '2026-07-20T12:00:00.000Z'


# ── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def client_user(django_user_model):
    """Create a client (parent) user."""
    from clients.models import Client
    user = django_user_model.objects.create_user(
        username='parent@example.com',
        email='parent@example.com',
        password='testpass123',
        first_name='Jane',
        last_name='Doe',
    )
    client = Client.objects.create(
        user=user,
        phone='555-1234',
    )
    return user


@pytest.fixture
def player(client_user):
    """Create a Player linked to the client_user."""
    from clients.models import Player, Client
    client = Client.objects.get(user=client_user)
    player = Player.objects.create(
        client=client,
        first_name='Alex',
        last_name='Doe',
        birth_year=2012,
        is_active=True,
    )
    return player


@pytest.fixture
def vald_profile(player):
    """Create a ValdProfile for the player."""
    profile = ValdProfile.objects.create(
        player=player,
        vald_profile_id='vald-test-123',
        vald_tenant_id='tenant-test-abc',
        match_method='manual',
    )
    return profile
