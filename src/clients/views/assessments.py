from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings

from clients.models import Client, Player
from coaches.models import PlayerAssessment


@login_required
def assessments_view(request):
    """View player assessments received from coaches."""
    client, created = Client.objects.get_or_create(user=request.user)
    players = client.players.filter(is_active=True)

    # Get all assessments for client's players
    assessments = PlayerAssessment.objects.filter(
        player__client=client
    ).select_related('player', 'coach', 'booking__session_type').order_by('-assessment_date')

    # Get VALD performance data if enabled
    vald_enabled = settings.VALD_SYNC_ENABLED
    vald_players = []
    if vald_enabled:
        try:
            from performance.models import ValdProfile, ValdTestResult
            for player in players:
                try:
                    profile = player.vald_profile
                    latest = profile.results.first()
                    total_count = profile.results.count()
                    vald_players.append({
                        'player': player,
                        'profile': profile,
                        'latest_test': latest,
                        'total_assessments': total_count,
                    })
                except ValdProfile.DoesNotExist:
                    pass
        except ImportError:
            vald_enabled = False

    context = {
        'client': client,
        'assessments': assessments,
        'vald_enabled': vald_enabled,
        'vald_players': vald_players,
    }
    return render(request, 'clients/assessments.html', context)


@login_required
def player_assessments(request, player_id):
    """View assessments for a specific player with time series chart."""
    from django.db.models import Avg
    client, created = Client.objects.get_or_create(user=request.user)
    player = get_object_or_404(Player, id=player_id, client=client)

    # Get all assessments for this player
    assessments_qs = PlayerAssessment.objects.filter(
        player=player
    ).select_related('coach', 'booking__session_type').order_by('-assessment_date')

    # Convert to list and add calculated overall rating
    assessments = []
    for a in assessments_qs:
        a.calc_overall = (a.effort_engagement + a.technical_proficiency +
                         a.tactical_awareness + a.physical_performance +
                         a.goals_achievement) / 5.0
        assessments.append(a)

    # Calculate averages for summary
    if assessments:
        averages = assessments_qs.aggregate(
            avg_effort=Avg('effort_engagement'),
            avg_technical=Avg('technical_proficiency'),
            avg_tactical=Avg('tactical_awareness'),
            avg_physical=Avg('physical_performance'),
            avg_goals=Avg('goals_achievement'),
        )
        # Calculate overall as average of all metrics
        if all(v is not None for v in averages.values()):
            averages['avg_overall'] = sum(averages.values()) / 5
        else:
            averages['avg_overall'] = None
    else:
        averages = {}

    context = {
        'client': client,
        'player': player,
        'assessments': assessments,
        'averages': averages,
        'total_assessments': len(assessments),
    }
    return render(request, 'clients/player_assessments.html', context)


@login_required
def player_assessment_chart_data(request, player_id):
    """API endpoint for player assessment chart data."""
    import json
    client, created = Client.objects.get_or_create(user=request.user)
    player = get_object_or_404(Player, id=player_id, client=client)

    # Get date range from query params
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    assessments = PlayerAssessment.objects.filter(player=player)

    if date_from:
        assessments = assessments.filter(assessment_date__gte=date_from)
    if date_to:
        assessments = assessments.filter(assessment_date__lte=date_to)

    assessments = assessments.order_by('assessment_date')

    # Build chart data
    data = {
        'labels': [],
        'datasets': {
            'overall': [],
            'effort': [],
            'technical': [],
            'tactical': [],
            'physical': [],
            'goals': [],
        }
    }

    for assessment in assessments:
        data['labels'].append(assessment.assessment_date.strftime('%b %d, %Y'))
        # Calculate overall as average of all 5 metrics
        overall = (assessment.effort_engagement + assessment.technical_proficiency +
                   assessment.tactical_awareness + assessment.physical_performance +
                   assessment.goals_achievement) / 5
        data['datasets']['overall'].append(round(overall, 2))
        data['datasets']['effort'].append(assessment.effort_engagement)
        data['datasets']['technical'].append(assessment.technical_proficiency)
        data['datasets']['tactical'].append(assessment.tactical_awareness)
        data['datasets']['physical'].append(assessment.physical_performance)
        data['datasets']['goals'].append(assessment.goals_achievement)

    return JsonResponse(data)
