from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q, Avg
from datetime import timedelta
from coaches.models import Coach, ScheduleBlock, PlayerAssessment
from bookings.models import Booking
from clients.models import Notification
from ._auth import coach_required


@coach_required
def assessments_list(request):
    """List sessions needing assessment with search and filter."""
    coach = request.coach
    today = timezone.localdate()

    # Get completed bookings without assessments (last 14 days)
    pending = Booking.objects.filter(
        coach=coach,
        status='completed',
        scheduled_date__gte=today - timedelta(days=30),
        scheduled_date__lte=today
    ).exclude(
        assessments__isnull=False
    ).select_related('player', 'session_type').order_by('-scheduled_date')

    # Base queryset for assessments
    assessments = PlayerAssessment.objects.filter(
        coach=coach
    ).select_related('player', 'booking__session_type')

    # Search by player name
    search_query = request.GET.get('search', '').strip()
    if search_query:
        assessments = assessments.filter(
            Q(player__first_name__icontains=search_query) |
            Q(player__last_name__icontains=search_query)
        )

    # Filter by training type
    training_type = request.GET.get('training_type', '')
    if training_type:
        assessments = assessments.filter(training_type=training_type)

    # Filter by rating
    min_rating = request.GET.get('min_rating', '')
    if min_rating:
        # Filter by calculated overall rating (approximate with average)
        from django.db.models import Avg
        assessments = assessments.annotate(
            avg_rating=Avg('effort_engagement') + Avg('technical_proficiency') +
                      Avg('tactical_awareness') + Avg('physical_performance') +
                      Avg('goals_achievement')
        )
        # Since overall is sum/5, multiply min_rating by 5
        assessments = assessments.filter(
            effort_engagement__gte=int(min_rating)
        )

    # Filter by date range
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if date_from:
        assessments = assessments.filter(assessment_date__date__gte=date_from)
    if date_to:
        assessments = assessments.filter(assessment_date__date__lte=date_to)

    # Order and limit
    assessments = assessments.order_by('-assessment_date')[:50]

    # Get unique players for filter dropdown — single subquery, no separate player_ids fetch
    from clients.models import Player
    from django.db.models import Avg
    players = Player.objects.filter(
        id__in=PlayerAssessment.objects.filter(coach=coach).values('player_id')
    ).order_by('first_name')

    # Calculate player averages for training decision support
    player_averages = PlayerAssessment.objects.filter(
        coach=coach
    ).values(
        'player__id', 'player__first_name', 'player__last_name'
    ).annotate(
        avg_effort=Avg('effort_engagement'),
        avg_technical=Avg('technical_proficiency'),
        avg_tactical=Avg('tactical_awareness'),
        avg_physical=Avg('physical_performance'),
        avg_goals=Avg('goals_achievement'),
        total_assessments=Count('id')
    ).order_by('player__first_name')

    # Calculate overall and identify weak/strong areas for each player
    for player in player_averages:
        scores = {
            'Effort': player['avg_effort'] or 0,
            'Technical': player['avg_technical'] or 0,
            'Tactical': player['avg_tactical'] or 0,
            'Physical': player['avg_physical'] or 0,
            'Goals': player['avg_goals'] or 0,
        }
        player['avg_overall'] = sum(scores.values()) / 5 if scores else 0
        player['weakest'] = min(scores, key=scores.get) if scores else None
        player['strongest'] = max(scores, key=scores.get) if scores else None
        player['weak_score'] = scores.get(player['weakest'], 0)
        player['strong_score'] = scores.get(player['strongest'], 0)

    context = {
        'coach': coach,
        'pending_assessments': pending,
        'recent_assessments': assessments,
        'players': players,
        'player_averages': player_averages,
        'training_types': PlayerAssessment.TRAINING_TYPE_CHOICES,
        'search_query': search_query,
        'selected_training_type': training_type,
        'selected_min_rating': min_rating,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'coaches/assessments.html', context)


@coach_required
def create_assessment(request, booking_id):
    """Create assessment for a booking."""
    coach = request.coach
    booking = get_object_or_404(Booking, id=booking_id, coach=coach)

    if request.method == 'POST':
        assessment = PlayerAssessment.objects.create(
            booking=booking,
            coach=coach,
            player=booking.player,
            training_type=request.POST.get('training_type', 'mixed'),
            effort_engagement=int(request.POST.get('effort_engagement', 3)),
            technical_proficiency=int(request.POST.get('technical_proficiency', 3)),
            tactical_awareness=int(request.POST.get('tactical_awareness', 3)),
            physical_performance=int(request.POST.get('physical_performance', 3)),
            goals_achievement=int(request.POST.get('goals_achievement', 3)),
            focus_areas=request.POST.get('focus_areas', ''),
            highlights=request.POST.get('highlights', ''),
            coach_notes=request.POST.get('coach_notes', ''),
            parent_visible_notes=request.POST.get('parent_visible_notes', ''),
        )

        # Send notification to parent
        try:
            prefs = booking.client.notification_preferences
            if prefs.assessment_notifications != 'none':
                Notification.objects.create(
                    client=booking.client,
                    notification_type='assessment_ready',
                    title=f'Assessment Ready for {booking.player.first_name}',
                    message=f'Coach {coach} has submitted an assessment for {booking.player}\'s training session on {booking.scheduled_date}.',
                    method=prefs.assessment_notifications,
                    booking=booking,
                )
                assessment.notification_sent = True
                assessment.save()
        except Exception:
            pass  # Notification preferences may not exist

        messages.success(request, f'Assessment submitted for {booking.player}!')
        return redirect('coaches:assessments')

    context = {
        'coach': coach,
        'booking': booking,
        'training_types': PlayerAssessment.TRAINING_TYPE_CHOICES,
        'rating_choices': PlayerAssessment.RATING_CHOICES,
    }
    return render(request, 'coaches/assessment_form.html', context)


@coach_required
def quick_assess_session(request, block_id):
    """Quick assessment for all players in a session."""
    coach = request.coach
    block = get_object_or_404(ScheduleBlock, id=block_id, coach=coach)

    # Get all completed bookings for this block — prefetch notification prefs to avoid N+1
    bookings = Booking.objects.filter(
        coach=coach,
        scheduled_date=block.date,
        scheduled_time=block.start_time,
        status='completed'
    ).exclude(
        assessments__isnull=False
    ).select_related('player', 'client').prefetch_related('client__notification_preferences')

    if request.method == 'POST':
        training_type = request.POST.get('training_type', 'mixed')
        assessments_created = 0

        for booking in bookings:
            effort = request.POST.get(f'effort_{booking.id}')
            technical = request.POST.get(f'technical_{booking.id}')
            tactical = request.POST.get(f'tactical_{booking.id}')
            physical = request.POST.get(f'physical_{booking.id}')
            goals = request.POST.get(f'goals_{booking.id}')

            if effort and technical and tactical and physical and goals:
                assessment = PlayerAssessment.objects.create(
                    booking=booking,
                    coach=coach,
                    player=booking.player,
                    training_type=training_type,
                    effort_engagement=int(effort),
                    technical_proficiency=int(technical),
                    tactical_awareness=int(tactical),
                    physical_performance=int(physical),
                    goals_achievement=int(goals),
                    parent_visible_notes=request.POST.get(f'notes_{booking.id}', ''),
                )

                # Send notification
                try:
                    prefs = booking.client.notification_preferences
                    if prefs.assessment_notifications != 'none':
                        Notification.objects.create(
                            client=booking.client,
                            notification_type='assessment_ready',
                            title=f'Assessment Ready for {booking.player.first_name}',
                            message=f'Coach {coach} has submitted an assessment for the training session.',
                            method=prefs.assessment_notifications,
                            booking=booking,
                        )
                        assessment.notification_sent = True
                        assessment.save()
                except Exception:
                    pass

                assessments_created += 1

        messages.success(request, f'{assessments_created} assessments submitted!')
        return redirect('coaches:todays_sessions')

    context = {
        'coach': coach,
        'block': block,
        'bookings': bookings,
        'training_types': PlayerAssessment.TRAINING_TYPE_CHOICES,
        'rating_choices': PlayerAssessment.RATING_CHOICES,
    }
    return render(request, 'coaches/quick_assess.html', context)
