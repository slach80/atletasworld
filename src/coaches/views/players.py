from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Count, Q, Avg
from coaches.models import Coach, PlayerAssessment
from bookings.models import Booking
from ._auth import coach_required


@coach_required
def my_players(request):
    """View all players that have trained with this coach."""
    coach = request.coach
    from clients.models import Player
    from django.db.models import Avg, Count, OuterRef, Subquery

    # Get last session date as subquery for efficient annotation
    last_session_subquery = Booking.objects.filter(
        coach=coach,
        player=OuterRef('pk')
    ).order_by('-scheduled_date').values('scheduled_date')[:1]

    # Get all players who have booked with this coach with aggregated stats
    players = Player.objects.filter(
        id__in=Booking.objects.filter(coach=coach).values('player_id').distinct(),
        is_active=True
    ).annotate(
        sessions_count=Count('bookings', filter=Q(bookings__coach=coach)),
        avg_effort=Avg('assessments__effort_engagement', filter=Q(assessments__coach=coach)),
        avg_technical=Avg('assessments__technical_proficiency', filter=Q(assessments__coach=coach)),
        avg_tactical=Avg('assessments__tactical_awareness', filter=Q(assessments__coach=coach)),
        avg_physical=Avg('assessments__physical_performance', filter=Q(assessments__coach=coach)),
        avg_goals=Avg('assessments__goals_achievement', filter=Q(assessments__coach=coach)),
        last_session_date=Subquery(last_session_subquery)
    ).order_by('-sessions_count')

    # Calculate overall average and prepare player data
    players_data = []
    for player in players:
        avg = 0
        if player.avg_effort is not None:
            avg = (
                (player.avg_effort or 0) +
                (player.avg_technical or 0) +
                (player.avg_tactical or 0) +
                (player.avg_physical or 0) +
                (player.avg_goals or 0)
            ) / 5

        players_data.append({
            'player': player,
            'sessions_count': player.sessions_count,
            'avg_rating': avg,
            'last_session_date': player.last_session_date,
        })

    context = {
        'coach': coach,
        'players': players_data,
        'total_sessions': Booking.objects.filter(coach=coach).count(),
        'assessments_count': PlayerAssessment.objects.filter(coach=coach).count(),
    }
    return render(request, 'coaches/my_players.html', context)


@coach_required
def player_detail(request, player_id):
    """View detailed info for a specific player."""
    coach = request.coach
    from clients.models import Player

    player = get_object_or_404(Player, id=player_id)

    # Check that this coach has trained this player
    bookings = Booking.objects.filter(
        coach=coach,
        player=player
    ).select_related('session_type').order_by('-scheduled_date')

    if not bookings.exists():
        messages.error(request, 'You have not trained this player.')
        return redirect('coaches:my_players')

    assessments = PlayerAssessment.objects.filter(
        coach=coach,
        player=player
    ).order_by('-assessment_date')

    context = {
        'coach': coach,
        'player': player,
        'bookings': bookings,
        'assessments': assessments,
    }
    return render(request, 'coaches/player_detail.html', context)
