"""
Tests for performance.tasks — VALD sync Celery tasks.

HTTP is mocked (never hits real VALD). Fixtures mirror the real API shapes
confirmed against VALD's live API during Phase 2 planning: /tests returns
metadata only, /trials carries the actual per-metric values.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import caches

from clients.models import Client, Player
from performance.models import ValdProfile, ValdResultDefinition, ValdSyncRun, ValdTestResult
from performance.tasks import _aggregate_best_of_trial, sync_forcedecks
from performance.vald_client import ValdAPIError

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

FIXTURES_DIR = Path(__file__).parent / 'fixtures'


def load_fixture(name):
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def clear_vald_locks():
    caches['vald'].clear()
    yield
    caches['vald'].clear()


@pytest.fixture
def player():
    user = get_user_model().objects.create_user(
        username='parent-sync@example.com', email='parent-sync@example.com',
        password='testpass123', first_name='Jane', last_name='Doe',
    )
    client = Client.objects.create(user=user, phone='555-1234')
    return Player.objects.create(client=client, first_name='Alex', last_name='Doe',
                                  birth_year=2012, is_active=True)


@pytest.fixture
def vald_profile(player):
    return ValdProfile.objects.create(
        player=player, vald_profile_id='profile-123', vald_tenant_id='tenant-abc',
        match_method='manual',
    )


@pytest.fixture
def result_definitions():
    ValdResultDefinition.objects.create(result_id='JUMP_HEIGHT', system='forcedecks',
                                         name='Jump Height', trend_direction='increasing')
    ValdResultDefinition.objects.create(result_id='CONTRACTION_TIME', system='forcedecks',
                                         name='Contraction Time', trend_direction='decreasing')
    ValdResultDefinition.objects.create(result_id='BODY_WEIGHT', system='forcedecks',
                                         name='Bodyweight', trend_direction='')


class TestAggregateBestOfTrial:
    """Best-of-trial aggregation across reps within one test."""

    def test_increasing_metric_takes_max(self):
        trials = load_fixture('forcedecks_trials.json')
        trend_by_id = {'JUMP_HEIGHT': 'increasing'}

        metrics = _aggregate_best_of_trial(trials, trend_by_id)

        assert metrics['JUMP_HEIGHT'] == 32.5  # max(28.5, 32.5)

    def test_decreasing_metric_takes_min(self):
        trials = load_fixture('forcedecks_trials.json')
        trend_by_id = {'CONTRACTION_TIME': 'decreasing'}

        metrics = _aggregate_best_of_trial(trials, trend_by_id)

        assert metrics['CONTRACTION_TIME'] == 0.278  # min(0.312, 0.278)

    def test_neutral_metric_takes_last_trial(self):
        trials = load_fixture('forcedecks_trials.json')
        trend_by_id = {}  # no definition known — neutral fallback

        metrics = _aggregate_best_of_trial(trials, trend_by_id)

        assert metrics['BODY_WEIGHT'] == 45.0


class TestSyncForcedecks:
    """Sync task: cursor pagination, aggregation, idempotency, error handling."""

    @patch('performance.tasks.vald_client.list_forcedecks_trials')
    @patch('performance.tasks.vald_client.list_forcedecks_tests')
    def test_upserts_test_result(self, mock_tests, mock_trials, vald_profile, result_definitions):
        test_obj = load_fixture('forcedecks_cmj.json')
        trials = load_fixture('forcedecks_trials.json')
        mock_tests.side_effect = [[test_obj], []]
        mock_trials.return_value = trials

        sync_forcedecks()

        assert ValdTestResult.objects.count() == 1
        result = ValdTestResult.objects.get(vald_test_id='test-cmj-001')
        assert result.profile == vald_profile
        assert result.test_type == 'CMJ'
        assert result.metrics['JUMP_HEIGHT'] == 32.5

        run = ValdSyncRun.objects.get(system='forcedecks')
        assert run.status == 'ok'
        assert run.records_synced == 1

    @patch('performance.tasks.vald_client.list_forcedecks_trials')
    @patch('performance.tasks.vald_client.list_forcedecks_tests')
    def test_rerun_is_idempotent(self, mock_tests, mock_trials, vald_profile, result_definitions):
        test_obj = load_fixture('forcedecks_cmj.json')
        trials = load_fixture('forcedecks_trials.json')
        mock_tests.side_effect = [[test_obj], [], [test_obj], []]
        mock_trials.return_value = trials

        sync_forcedecks()
        sync_forcedecks()

        assert ValdTestResult.objects.count() == 1

    @patch('performance.tasks.vald_client.list_forcedecks_trials')
    @patch('performance.tasks.vald_client.list_forcedecks_tests')
    def test_unmatched_profile_is_skipped_not_failed(self, mock_tests, mock_trials, result_definitions):
        """No ValdProfile exists for this profileId — should skip, not crash the run."""
        test_obj = load_fixture('forcedecks_cmj.json')
        assert test_obj['profileId'] == 'profile-123'  # sanity: no matching ValdProfile created in this test
        mock_tests.side_effect = [[test_obj], []]
        mock_trials.return_value = []

        sync_forcedecks()

        assert ValdTestResult.objects.count() == 0
        run = ValdSyncRun.objects.get(system='forcedecks')
        assert run.status == 'ok'
        assert run.records_synced == 0

    @patch('performance.tasks.vald_client.list_forcedecks_tests')
    def test_api_error_marks_run_failed_and_reraises(self, mock_tests):
        mock_tests.side_effect = ValdAPIError('boom')

        with pytest.raises(ValdAPIError):
            sync_forcedecks()

        run = ValdSyncRun.objects.get(system='forcedecks')
        assert run.status == 'error'
        assert 'boom' in run.error

    @patch('performance.tasks.vald_client.list_forcedecks_tests')
    def test_concurrent_run_skips_when_locked(self, mock_tests):
        caches['vald'].add('vald:sync_lock:forcedecks', 1, timeout=1800)

        sync_forcedecks()

        mock_tests.assert_not_called()
        assert ValdSyncRun.objects.filter(system='forcedecks').count() == 0
