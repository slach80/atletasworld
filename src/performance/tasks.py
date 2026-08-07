"""
Celery tasks for VALD Performance sync.

Order matters: profiles first (ForceDecks tests FK to ValdProfile via
profileId), then ForceDecks. A test for an unmatched profile is logged and
skipped, not failed, so the rest of the batch still lands.
"""
import io
import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import caches
from django.core.management import call_command
from django.utils.dateparse import parse_datetime

from . import vald_client
from .models import ValdProfile, ValdResultDefinition, ValdSyncRun, ValdTestResult

logger = logging.getLogger(__name__)

LOCK_TIMEOUT = 30 * 60  # 30 minutes — matches CELERY_TASK_TIME_LIMIT


def _acquire_lock(system):
    """Cache-based, atomic set-if-absent lock so a manual 'Sync Now' click
    can't race the nightly beat run for the same system."""
    return caches['vald'].add(f'vald:sync_lock:{system}', 1, timeout=LOCK_TIMEOUT)


def _release_lock(system):
    caches['vald'].delete(f'vald:sync_lock:{system}')


@shared_task(name='performance.tasks.sync_all_vald')
def sync_all_vald():
    """Orchestrator: profiles then ForceDecks, each independently locked and
    error-isolated so a failure in one doesn't block the other."""
    sync_profiles()
    sync_forcedecks()


@shared_task(name='performance.tasks.sync_profiles')
def sync_profiles():
    """Auto-link unambiguous VALD profile matches via the existing
    vald_match_profiles command — reuses its ambiguous-match safety rather
    than duplicating the matching logic here."""
    if not _acquire_lock('profiles'):
        logger.info('VALD profiles sync already running, skipping')
        return

    try:
        out = io.StringIO()
        call_command('vald_match_profiles', stdout=out)
        logger.info('VALD profile match run:\n%s', out.getvalue())
    except Exception:
        logger.exception('VALD profile matching failed')
        raise
    finally:
        _release_lock('profiles')


@shared_task(name='performance.tasks.sync_forcedecks')
def sync_forcedecks():
    """Incremental ForceDecks sync: cursor-paginate /tests, pull /trials for
    each, best-of-trial aggregate into ValdTestResult."""
    if not _acquire_lock('forcedecks'):
        logger.info('VALD ForceDecks sync already running, skipping')
        return

    run = ValdSyncRun.objects.create(system='forcedecks')
    try:
        trend_by_id = dict(
            ValdResultDefinition.objects.values_list('result_id', 'trend_direction')
        )

        cursor = ValdSyncRun.cursor('forcedecks')
        upserted = 0
        max_seen = cursor

        while True:
            tests = vald_client.list_forcedecks_tests(
                settings.VALD_TENANT_ID, modified_from_utc=cursor
            )
            if not tests:
                break

            for test in tests:
                upserted += _sync_one_test(test, trend_by_id)

            new_cursor = max(t['modifiedDateUtc'] for t in tests)
            max_seen = max(max_seen, new_cursor)
            if new_cursor == cursor:
                # No forward progress — avoid looping forever on an
                # inclusive-boundary response from the API.
                break
            cursor = new_cursor

        run.finish_ok(upserted, last_synced_at=parse_datetime(max_seen))
    except Exception as e:
        logger.exception('ForceDecks sync failed')
        run.finish_error(str(e))
        raise
    finally:
        _release_lock('forcedecks')


def _sync_one_test(test, trend_by_id):
    """Fetch trials for one test, aggregate best-of-trial per metric, and
    upsert into ValdTestResult. Returns 1 if upserted, 0 if skipped
    (unmatched profile)."""
    try:
        profile = ValdProfile.objects.get(
            vald_profile_id=test['profileId'], is_active=True
        )
    except ValdProfile.DoesNotExist:
        logger.info(
            'Skipping VALD test %s — no matching ValdProfile for profileId %s',
            test['testId'], test['profileId'],
        )
        return 0

    trials = vald_client.list_forcedecks_trials(settings.VALD_TENANT_ID, test['testId'])
    metrics = _aggregate_best_of_trial(trials, trend_by_id)

    test_date = parse_datetime(test['recordedDateUtc'])

    result, _created = ValdTestResult.objects.update_or_create(
        vald_test_id=test['testId'],
        defaults={
            'profile': profile,
            'system': 'forcedecks',
            'test_type': test.get('testType', ''),
            'test_date': test_date,
            'raw_payload': {'test': test, 'trials': trials},
            'metrics': metrics,
            'week_key': test_date.strftime('%G-W%V'),
        },
    )
    return 1


def _aggregate_best_of_trial(trials, trend_by_id):
    """Pick one value per metric across all trials (reps) of a test.

    'increasing' trend -> max across trials; 'decreasing' -> min; unknown or
    neutral polarity -> last trial's value (arbitrary tie-break, only affects
    metrics that aren't chart-curated).
    """
    values_by_metric = {}
    for trial in trials:
        for r in trial.get('results', []):
            result_id = r.get('definition', {}).get('result')
            if not result_id:
                continue
            values_by_metric.setdefault(result_id, []).append(r['value'])

    metrics = {}
    for result_id, values in values_by_metric.items():
        trend = trend_by_id.get(result_id)
        if trend == 'increasing':
            metrics[result_id] = max(values)
        elif trend == 'decreasing':
            metrics[result_id] = min(values)
        else:
            metrics[result_id] = values[-1]
    return metrics
