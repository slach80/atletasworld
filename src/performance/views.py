"""
VALD Performance views — client portal and owner portal.

Client views: parent sees their own players' metrics only.
Owner views: admin sees all players, sync controls, match UI.
"""
from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.db.models import Max, Count

from clients.models import Player
from .models import ValdProfile, ValdTestResult, ValdResultDefinition, ValdSyncRun
from .decorators import require_vald_enabled


def _manual_test_groups_for_player(player):
    """Group ManualTestResult entries (Bleep Test, etc.) by test type, chart-ready.

    Independent of VALD_SYNC_ENABLED — these results don't come from VALD.
    """
    from coaches.models import ManualTestResult

    results = ManualTestResult.objects.filter(player=player).order_by('test_date')
    valid_types = dict(ManualTestResult.TEST_TYPE_CHOICES)
    groups = []
    for type_value, type_label in valid_types.items():
        type_results = [r for r in results if r.test_type == type_value]
        if not type_results:
            continue

        values = [float(r.value) for r in type_results]
        latest_value = values[-1]

        # Delta vs previous test
        delta = None
        delta_percent = None
        if len(values) >= 2:
            delta = latest_value - values[-2]
            if values[-2] != 0:
                delta_percent = (delta / values[-2]) * 100

        # Overall change vs first test on record
        overall_change = None
        overall_percent = None
        if len(values) >= 2:
            overall_change = latest_value - values[0]
            if values[0] != 0:
                overall_percent = (overall_change / values[0]) * 100

        groups.append({
            'test_type': type_value,
            'label': type_label,
            'unit': type_results[-1].unit,
            'latest_value': latest_value,
            'count': len(type_results),
            'results': list(reversed(type_results)),  # newest first, for list display
            'delta': delta,
            'delta_percent': delta_percent,
            'overall_change': overall_change,
            'overall_percent': overall_percent,
            'chart_points': [
                {'formatted_date': r.test_date.strftime('%b %d, %Y'), 'value': float(r.value)}
                for r in type_results
            ],
        })
    return groups


# ── Helper ──────────────────────────────────────────────────────────────────
def is_owner(user):
    """Check if user is owner (staff/superuser OR in Owner group)."""
    # Import here to avoid circular dependency
    from atletasworld.owner_views._auth import is_owner as owner_check
    return owner_check(user)


# ── Client Portal Views ─────────────────────────────────────────────────────
@login_required
def player_performance(request):
    """
    Smart redirect for performance page.

    - If user has exactly 1 player → go to that player's detail page
    - Otherwise → go to assessments page (where VALD data is integrated)
    """
    from django.shortcuts import redirect

    # Check if user has exactly one player
    players = Player.objects.filter(
        client__user=request.user,
        is_active=True
    )

    if players.count() == 1:
        # Single player - go straight to their performance detail
        player = players.first()
        return redirect('performance_detail', player_id=player.id)
    else:
        # Multiple players or no players - show assessments page with VALD section
        return redirect('clients:assessments')


@login_required
def player_detail(request, player_id):
    """
    Client portal: per-player performance metrics and charts.

    IDOR protection: only the player's own parent (client__user=request.user).

    Not gated behind VALD_SYNC_ENABLED — manual test results (Bleep Test, etc.)
    are independent of the VALD integration and must still show when it's off.
    """
    from datetime import timedelta
    from django.utils import timezone

    player = get_object_or_404(
        Player,
        pk=player_id,
        client__user=request.user,
        is_active=True
    )

    # Time frame filtering
    timeframe = request.GET.get('timeframe', 'all')
    now = timezone.now()

    timeframe_filters = {
        '4w': now - timedelta(weeks=4),
        '3m': now - timedelta(days=90),
        '6m': now - timedelta(days=180),
        '1y': now - timedelta(days=365),
        'all': None,
    }

    since_date = timeframe_filters.get(timeframe)

    profile = None
    results = []
    metrics_data = []
    is_eligible = False
    eligibility_reason = "VALD integration is not enabled"

    if settings.VALD_SYNC_ENABLED:
        try:
            profile = player.vald_profile
            # CMJ-only for now — SLJ and box-drop share result IDs (e.g.
            # JUMP_HEIGHT_INCHES) with CMJ, so mixing test types here would
            # blend unrelated jump types into the same chart once those land.
            results_qs = profile.results.filter(test_type='CMJ')

            # Apply time filter
            if since_date:
                results_qs = results_qs.filter(test_date__gte=since_date)

            results = results_qs.order_by('test_date')

            # Get visible metric definitions
            definitions = ValdResultDefinition.objects.filter(
                show_in_client_portal=True
            ).order_by('system', 'display_order')

            # Build metric charts data
            metrics_data = []
            for defn in definitions:
                # Extract this metric's values from results
                points = []
                for result in results:
                    value = result.metrics.get(defn.result_id)
                    if value is not None:
                        points.append({
                            'date': result.test_date.isoformat(),
                            'value': value,
                            'week': result.week_key,
                            'formatted_date': result.test_date.strftime('%b %d, %Y'),
                        })

                if points:  # Only include metrics with data
                    # Calculate delta and percentage change (latest vs previous)
                    delta = None
                    delta_percent = None
                    if len(points) >= 2:
                        latest_val = points[-1]['value']
                        prev_val = points[-2]['value']
                        delta = latest_val - prev_val
                        if prev_val != 0:
                            delta_percent = (delta / prev_val) * 100

                    # Calculate overall improvement (first vs latest)
                    overall_change = None
                    overall_percent = None
                    if len(points) >= 2:
                        first_val = points[0]['value']
                        latest_val = points[-1]['value']
                        overall_change = latest_val - first_val
                        if first_val != 0:
                            overall_percent = (overall_change / first_val) * 100

                    metrics_data.append({
                        'definition': defn,
                        'points': points,
                        'latest': points[-1]['value'] if points else None,
                        'delta': delta,
                        'delta_percent': delta_percent,
                        'overall_change': overall_change,
                        'overall_percent': overall_percent,
                        'count': len(points),
                        'first_value': points[0]['value'] if points else None,
                    })

            # Eligibility logic (simplified for Phase 1)
            # TODO: integrate with ClientPackage / select_teams in Phase 2
            is_eligible = False
            eligibility_reason = "Contact us to book an assessment"

        except ValdProfile.DoesNotExist:
            profile = None
            results = []
            metrics_data = []
            is_eligible = False
            eligibility_reason = "Profile not linked yet"

    manual_test_groups = _manual_test_groups_for_player(player)

    context = {
        'player': player,
        'profile': profile,
        'results_count': len(results),
        'latest_test': results[0] if results else None,
        'metrics_data': metrics_data,
        'manual_test_groups': manual_test_groups,
        'is_eligible': is_eligible,
        'eligibility_reason': eligibility_reason,
        'timeframe': timeframe,
    }
    return render(request, 'performance/detail.html', context)


# ── Owner Portal Views ──────────────────────────────────────────────────────
@user_passes_test(is_owner)
@require_vald_enabled
def owner_performance(request):
    """
    Owner portal: table of all players with VALD metrics + sync controls.
    """
    players = Player.objects.filter(is_active=True).select_related(
        'client__user'
    ).prefetch_related('vald_profile__results')

    player_data = []
    for player in players:
        try:
            profile = player.vald_profile
            latest = profile.results.first()
            total_count = profile.results.count()

            player_data.append({
                'player': player,
                'profile': profile,
                'latest_test': latest,
                'total_assessments': total_count,
                'sync_status': 'ok',  # TODO: derive from ValdSyncRun
            })
        except ValdProfile.DoesNotExist:
            player_data.append({
                'player': player,
                'profile': None,
                'latest_test': None,
                'total_assessments': 0,
                'sync_status': 'unmatched',
            })

    # Recent sync runs
    recent_syncs = ValdSyncRun.objects.all()[:10]

    context = {
        'player_data': player_data,
        'recent_syncs': recent_syncs,
    }
    return render(request, 'owner/performance.html', context)


@user_passes_test(is_owner)
def owner_player_detail(request, player_id):
    """
    Owner portal: per-player detail + raw payload + match UI.

    Not gated behind VALD_SYNC_ENABLED — manual test results (Bleep Test, etc.)
    are independent of the VALD integration and must still show when it's off.
    """
    player = get_object_or_404(Player, pk=player_id, is_active=True)

    profile = None
    results = []
    metrics_data = []

    if settings.VALD_SYNC_ENABLED:
        try:
            profile = player.vald_profile
            # CMJ-only for now — see comment in player_detail().
            results = profile.results.filter(test_type='CMJ').order_by('test_date')

            # Get ALL metric definitions (owner sees everything)
            definitions = ValdResultDefinition.objects.all().order_by('system', 'display_order')

            metrics_data = []
            for defn in definitions:
                points = []
                for result in results:
                    value = result.metrics.get(defn.result_id)
                    if value is not None:
                        points.append({
                            'date': result.test_date.isoformat(),
                            'value': value,
                            'week': result.week_key,
                        })

                if points:
                    delta = None
                    delta_percent = None
                    if len(points) >= 2:
                        latest_val = points[-1]['value']
                        prev_val = points[-2]['value']
                        delta = latest_val - prev_val
                        if prev_val != 0:
                            delta_percent = (delta / prev_val) * 100

                    overall_change = None
                    overall_percent = None
                    if len(points) >= 2:
                        first_val = points[0]['value']
                        latest_val = points[-1]['value']
                        overall_change = latest_val - first_val
                        if first_val != 0:
                            overall_percent = (overall_change / first_val) * 100

                    metrics_data.append({
                        'definition': defn,
                        'points': points,
                        'latest': points[-1]['value'],
                        'count': len(points),
                        'delta': delta,
                        'delta_percent': delta_percent,
                        'overall_change': overall_change,
                        'overall_percent': overall_percent,
                    })

        except ValdProfile.DoesNotExist:
            profile = None
            results = []
            metrics_data = []

    manual_test_groups = _manual_test_groups_for_player(player)

    # Sync history for this profile
    sync_runs = ValdSyncRun.objects.all()[:5]

    context = {
        'player': player,
        'profile': profile,
        'results': results,
        'metrics_data': metrics_data,
        'manual_test_groups': manual_test_groups,
        'sync_runs': sync_runs,
    }
    return render(request, 'owner/performance_detail.html', context)


@user_passes_test(is_owner)
@require_POST
@require_vald_enabled
def owner_trigger_sync(request):
    """
    Owner portal: manually trigger a VALD sync (all systems).

    Dispatches the Celery task and redirects back to owner_performance.
    """
    # TODO: import and dispatch sync_all_vald.delay() when tasks.py is built
    # For Phase 1: just redirect with a message
    from django.contrib import messages
    messages.info(request, 'Manual sync will be implemented in Phase 2 (Celery tasks)')
    return HttpResponseRedirect(reverse('owner_performance'))


@user_passes_test(is_owner)
@require_POST
@require_vald_enabled
def owner_match_profile(request, player_id):
    """
    Owner portal: manually link a Player to a VALD profile.

    Expects POST with 'vald_profile_id' and 'vald_tenant_id'.
    """
    player = get_object_or_404(Player, pk=player_id, is_active=True)

    vald_profile_id = request.POST.get('vald_profile_id')
    vald_tenant_id = request.POST.get('vald_tenant_id')

    if not vald_profile_id or not vald_tenant_id:
        return JsonResponse({'error': 'Missing profile or tenant ID'}, status=400)

    # Create or update ValdProfile
    profile, created = ValdProfile.objects.update_or_create(
        player=player,
        defaults={
            'vald_profile_id': vald_profile_id,
            'vald_tenant_id': vald_tenant_id,
            'match_method': 'manual',
            'is_active': True,
        }
    )

    return JsonResponse({
        'success': True,
        'created': created,
        'profile_id': profile.vald_profile_id,
    })
