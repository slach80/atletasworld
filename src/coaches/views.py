from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Count, Q, Avg
from django.db import models
from datetime import datetime, timedelta, time
from .models import Coach, ScheduleBlock, SessionAttendance, PlayerAssessment
from bookings.models import Booking
from clients.models import Notification


def coach_required(view_func):
    """Decorator to ensure user is a coach with proper group membership."""
    @login_required
    def wrapper(request, *args, **kwargs):
        # Check user is in Coach group
        if not request.user.groups.filter(name='Coach').exists():
            messages.error(request, 'You do not have coach access.')
            return redirect('home')

        # Get associated Coach profile
        try:
            request.coach = Coach.objects.get(user=request.user)
            if not request.coach.is_active:
                messages.error(request, 'Your coach account is not active.')
                return redirect('home')
        except Coach.DoesNotExist:
            messages.error(request, 'Coach profile not found.')
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return wrapper


@coach_required
def dashboard(request):
    """Coach dashboard with overview."""
    coach = request.coach
    today = timezone.now().date()

    # Today's sessions
    todays_blocks = ScheduleBlock.objects.filter(
        coach=coach,
        date=today,
        status__in=['available', 'booked']
    ).prefetch_related('attendances__booking__player')

    # Upcoming sessions (next 7 days)
    upcoming_blocks = ScheduleBlock.objects.filter(
        coach=coach,
        date__gt=today,
        date__lte=today + timedelta(days=7),
        status__in=['available', 'booked']
    ).order_by('date', 'start_time')[:10]

    # Pending assessments (sessions completed but not assessed)
    pending_assessments = Booking.objects.filter(
        coach=coach,
        status='completed',
        scheduled_date__gte=today - timedelta(days=7)
    ).exclude(
        assessments__isnull=False
    ).select_related('player', 'session_type')[:10]

    # Stats
    stats = {
        'todays_sessions': todays_blocks.count(),
        'weeks_sessions': upcoming_blocks.count(),
        'pending_assessments': pending_assessments.count(),
        'total_students_this_month': Booking.objects.filter(
            coach=coach,
            scheduled_date__month=today.month,
            scheduled_date__year=today.year
        ).values('player').distinct().count(),
    }

    context = {
        'coach': coach,
        'todays_blocks': todays_blocks,
        'upcoming_blocks': upcoming_blocks,
        'pending_assessments': pending_assessments,
        'stats': stats,
        'today': today,
    }
    return render(request, 'coaches/dashboard.html', context)


@coach_required
def schedule(request):
    """View and manage schedule."""
    coach = request.coach
    today = timezone.now().date()

    # Get date range from query params
    start_date = request.GET.get('start', today.isoformat())
    try:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    except ValueError:
        start_date = today

    end_date = start_date + timedelta(days=6)

    # Get schedule blocks for the week
    blocks = ScheduleBlock.objects.filter(
        coach=coach,
        date__gte=start_date,
        date__lte=end_date
    ).order_by('date', 'start_time')

    # Check for overlaps with other coaches
    overlap_warnings = []
    for block in blocks:
        overlaps = block.check_overlap_warnings()
        if overlaps.exists():
            overlap_warnings.append({
                'block': block,
                'overlapping_coaches': [o.coach for o in overlaps]
            })

    # Generate week days for the calendar view
    week_days = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        day_blocks = [b for b in blocks if b.date == day]
        week_days.append({
            'date': day,
            'day_name': day.strftime('%A'),
            'blocks': day_blocks,
        })

    context = {
        'coach': coach,
        'week_days': week_days,
        'start_date': start_date,
        'end_date': end_date,
        'prev_week': (start_date - timedelta(days=7)).isoformat(),
        'next_week': (start_date + timedelta(days=7)).isoformat(),
        'overlap_warnings': overlap_warnings,
        'session_types': ScheduleBlock.SESSION_TYPE_CHOICES,
        'duration_choices': ScheduleBlock.DURATION_CHOICES,
    }
    return render(request, 'coaches/schedule.html', context)


@coach_required
def add_schedule_block(request):
    """Add a new schedule block."""
    coach = request.coach

    if request.method == 'POST':
        date_str = request.POST.get('date')
        start_time_str = request.POST.get('start_time')
        session_type = request.POST.get('session_type', 'private')
        duration = int(request.POST.get('duration', 60))
        max_participants = int(request.POST.get('max_participants', 1))

        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_time = datetime.strptime(start_time_str, '%H:%M').time()

            # Calculate end time
            start_dt = datetime.combine(date, start_time)
            end_dt = start_dt + timedelta(minutes=duration)
            end_time = end_dt.time()

            # For private sessions, max_participants is always 1
            if session_type == 'private':
                max_participants = 1

            block = ScheduleBlock.objects.create(
                coach=coach,
                date=date,
                start_time=start_time,
                end_time=end_time,
                session_type=session_type,
                duration_minutes=duration,
                max_participants=max_participants,
            )

            # Check for overlaps
            overlaps = block.check_overlap_warnings()
            if overlaps.exists():
                coach_names = ', '.join([str(o.coach) for o in overlaps])
                messages.warning(request, f'Note: This time overlaps with sessions from: {coach_names}')

            messages.success(request, 'Schedule block added successfully!')

        except Exception as e:
            messages.error(request, f'Error adding schedule block: {str(e)}')

        return redirect('coaches:schedule')

    return redirect('coaches:schedule')


@coach_required
def add_bulk_schedule(request):
    """Add multiple schedule blocks at once (whole time blocks)."""
    coach = request.coach

    if request.method == 'POST':
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        days_of_week = request.POST.getlist('days_of_week')  # [0, 1, 2, ...]
        start_time_str = request.POST.get('start_time')
        end_time_str = request.POST.get('end_time')
        session_type = request.POST.get('session_type', 'private')
        duration = int(request.POST.get('duration', 60))
        max_participants = int(request.POST.get('max_participants', 1))

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            block_start_time = datetime.strptime(start_time_str, '%H:%M').time()
            block_end_time = datetime.strptime(end_time_str, '%H:%M').time()

            if session_type == 'private':
                max_participants = 1

            blocks_created = 0
            current_date = start_date

            while current_date <= end_date:
                if str(current_date.weekday()) in days_of_week:
                    # Create blocks for this day
                    current_time = datetime.combine(current_date, block_start_time)
                    day_end = datetime.combine(current_date, block_end_time)

                    while current_time + timedelta(minutes=duration) <= day_end:
                        slot_end = current_time + timedelta(minutes=duration)

                        # Check if block already exists
                        if not ScheduleBlock.objects.filter(
                            coach=coach,
                            date=current_date,
                            start_time=current_time.time()
                        ).exists():
                            ScheduleBlock.objects.create(
                                coach=coach,
                                date=current_date,
                                start_time=current_time.time(),
                                end_time=slot_end.time(),
                                session_type=session_type,
                                duration_minutes=duration,
                                max_participants=max_participants,
                            )
                            blocks_created += 1

                        current_time = slot_end

                current_date += timedelta(days=1)

            messages.success(request, f'{blocks_created} schedule blocks created successfully!')

        except Exception as e:
            messages.error(request, f'Error creating schedule: {str(e)}')

        return redirect('coaches:schedule')

    # GET request - show form
    context = {
        'coach': coach,
        'session_types': ScheduleBlock.SESSION_TYPE_CHOICES,
        'duration_choices': ScheduleBlock.DURATION_CHOICES,
        'days_of_week': [
            (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'),
            (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday')
        ],
    }
    return render(request, 'coaches/bulk_schedule.html', context)


@coach_required
@require_POST
def delete_schedule_block(request, block_id):
    """Delete a schedule block."""
    coach = request.coach
    block = get_object_or_404(ScheduleBlock, id=block_id, coach=coach)

    if block.current_participants > 0:
        messages.error(request, 'Cannot delete a block with bookings. Cancel the bookings first.')
    else:
        block.delete()
        messages.success(request, 'Schedule block deleted.')

    return redirect('coaches:schedule')


@coach_required
def session_attendance(request, block_id):
    """View and manage attendance for a session."""
    coach = request.coach
    block = get_object_or_404(ScheduleBlock, id=block_id, coach=coach)

    # Get all bookings for this block
    bookings = Booking.objects.filter(
        coach=coach,
        scheduled_date=block.date,
        scheduled_time=block.start_time,
        status__in=['pending', 'confirmed', 'completed']
    ).select_related('player', 'client')

    # Get or create attendance records
    attendances = []
    for booking in bookings:
        attendance, created = SessionAttendance.objects.get_or_create(
            schedule_block=block,
            booking=booking,
            defaults={'status': 'expected'}
        )
        attendances.append({
            'booking': booking,
            'attendance': attendance,
        })

    context = {
        'coach': coach,
        'block': block,
        'attendances': attendances,
        'attendance_statuses': SessionAttendance.ATTENDANCE_STATUS,
    }
    return render(request, 'coaches/attendance.html', context)


@coach_required
@require_POST
def update_attendance(request, attendance_id):
    """Update attendance status for a player."""
    coach = request.coach
    attendance = get_object_or_404(SessionAttendance, id=attendance_id, schedule_block__coach=coach)

    status = request.POST.get('status')
    if status in dict(SessionAttendance.ATTENDANCE_STATUS):
        attendance.status = status
        if status == 'present':
            attendance.check_in_time = timezone.now()
        attendance.save()

        # Update booking status if marked present/completed
        if status in ['present', 'late']:
            attendance.booking.status = 'completed'
            attendance.booking.save()

        messages.success(request, f'Attendance updated for {attendance.booking.player}')

    return redirect('coaches:session_attendance', block_id=attendance.schedule_block.id)


@coach_required
def todays_sessions(request):
    """Quick view of today's sessions grouped by time block."""
    coach = request.coach
    today = timezone.now().date()

    blocks = ScheduleBlock.objects.filter(
        coach=coach,
        date=today
    ).order_by('start_time')

    # Get bookings for each block
    blocks_with_players = []
    for block in blocks:
        bookings = Booking.objects.filter(
            coach=coach,
            scheduled_date=today,
            scheduled_time=block.start_time,
            status__in=['pending', 'confirmed']
        ).select_related('player', 'client')

        blocks_with_players.append({
            'block': block,
            'bookings': bookings,
        })

    context = {
        'coach': coach,
        'today': today,
        'blocks_with_players': blocks_with_players,
    }
    return render(request, 'coaches/todays_sessions.html', context)


@coach_required
def assessments_list(request):
    """List sessions needing assessment with search and filter."""
    coach = request.coach
    today = timezone.now().date()

    # Get completed bookings without assessments (last 14 days)
    pending = Booking.objects.filter(
        coach=coach,
        status='completed',
        scheduled_date__gte=today - timedelta(days=14),
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

    # Get unique players for filter dropdown
    player_ids = PlayerAssessment.objects.filter(coach=coach).values_list('player_id', flat=True).distinct()
    from clients.models import Player
    from django.db.models import Avg
    players = Player.objects.filter(id__in=player_ids).order_by('first_name')

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

    # Get all completed bookings for this block
    bookings = Booking.objects.filter(
        coach=coach,
        scheduled_date=block.date,
        scheduled_time=block.start_time,
        status='completed'
    ).exclude(
        assessments__isnull=False
    ).select_related('player', 'client')

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


@coach_required
def my_players(request):
    """View all players that have trained with this coach."""
    coach = request.coach
    from clients.models import Player
    from django.db.models import Avg

    # Get all players who have booked with this coach
    player_ids = Booking.objects.filter(
        coach=coach
    ).values_list('player_id', flat=True).distinct()

    players_data = []
    for player in Player.objects.filter(id__in=player_ids, is_active=True):
        bookings = Booking.objects.filter(coach=coach, player=player)
        assessments = PlayerAssessment.objects.filter(coach=coach, player=player)
        avg_rating = assessments.aggregate(
            avg=Avg('effort_engagement') + Avg('technical_proficiency') +
                Avg('tactical_awareness') + Avg('physical_performance') +
                Avg('goals_achievement')
        )
        # Calculate proper average
        if assessments.exists():
            total = sum([
                assessments.aggregate(Avg('effort_engagement'))['effort_engagement__avg'] or 0,
                assessments.aggregate(Avg('technical_proficiency'))['technical_proficiency__avg'] or 0,
                assessments.aggregate(Avg('tactical_awareness'))['tactical_awareness__avg'] or 0,
                assessments.aggregate(Avg('physical_performance'))['physical_performance__avg'] or 0,
                assessments.aggregate(Avg('goals_achievement'))['goals_achievement__avg'] or 0,
            ])
            avg = total / 5
        else:
            avg = 0

        players_data.append({
            'player': player,
            'sessions_count': bookings.count(),
            'avg_rating': avg,
            'last_session': bookings.order_by('-scheduled_date').first(),
        })

    # Sort by most sessions
    players_data.sort(key=lambda x: x['sessions_count'], reverse=True)

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


@coach_required
def notify_parents(request):
    """Page to send notifications to parents."""
    coach = request.coach
    from clients.models import Player, Client

    # Get all unique clients from players coached
    player_ids = Booking.objects.filter(
        coach=coach
    ).values_list('player_id', flat=True).distinct()

    clients = Client.objects.filter(
        players__id__in=player_ids
    ).distinct().prefetch_related('players')

    context = {
        'coach': coach,
        'clients': clients,
    }
    return render(request, 'coaches/notify_parents.html', context)


@coach_required
@require_POST
def send_notification(request):
    """Send notifications to multiple players' parents."""
    coach = request.coach
    from clients.models import Player

    player_ids = request.POST.getlist('player_ids')
    notification_type = request.POST.get('notification_type', 'general')
    message = request.POST.get('message', '')

    if player_ids and message:
        # Get unique clients from selected players
        players = Player.objects.filter(id__in=player_ids).select_related('client')
        notified_clients = set()
        sent_count = 0

        for player in players:
            client = player.client
            # Avoid sending duplicate notifications to the same client
            if client.id in notified_clients:
                continue
            notified_clients.add(client.id)

            # Get notification preference
            try:
                prefs = client.notification_preferences
                method = prefs.booking_confirmations
            except Exception:
                method = 'email'

            # Create notification
            Notification.objects.create(
                client=client,
                notification_type='promotional' if notification_type == 'general' else notification_type,
                title=f'Message from Coach {coach.user.first_name}',
                message=message,
                method=method,
            )
            sent_count += 1

        if sent_count == 1:
            messages.success(request, f'Notification sent to 1 parent!')
        else:
            messages.success(request, f'Notification sent to {sent_count} parents!')
    else:
        messages.error(request, 'Please select recipients and provide a message.')

    return redirect('coaches:notify_parents')


@coach_required
def availability(request):
    """Coach availability calendar using Toast UI Calendar."""
    coach = request.coach
    context = {
        'coach': coach,
    }
    return render(request, 'coaches/availability.html', context)


@coach_required
def edit_profile(request):
    """Coach profile edit page - only accessible if profile_enabled."""
    coach = request.coach

    if not coach.profile_enabled:
        messages.error(request, 'Your public profile has not been enabled yet. Please contact the administrator.')
        return redirect('coaches:dashboard')

    if request.method == 'POST':
        # Update coach profile fields (only the coach-editable fields)
        coach.tagline = request.POST.get('tagline', '')[:200]
        coach.full_bio = request.POST.get('full_bio', '')
        coach.experience_years = int(request.POST.get('experience_years', 0) or 0)
        coach.coaching_philosophy = request.POST.get('coaching_philosophy', '')
        coach.achievements = request.POST.get('achievements', '')

        # Social links
        coach.instagram_url = request.POST.get('instagram_url', '')
        coach.facebook_url = request.POST.get('facebook_url', '')
        coach.twitter_url = request.POST.get('twitter_url', '')
        coach.linkedin_url = request.POST.get('linkedin_url', '')
        coach.youtube_url = request.POST.get('youtube_url', '')
        coach.personal_website = request.POST.get('personal_website', '')

        # Handle photo upload
        if 'photo' in request.FILES:
            coach.photo = request.FILES['photo']

        # Handle gallery images
        if 'gallery_image_1' in request.FILES:
            coach.gallery_image_1 = request.FILES['gallery_image_1']
        if 'gallery_image_2' in request.FILES:
            coach.gallery_image_2 = request.FILES['gallery_image_2']
        if 'gallery_image_3' in request.FILES:
            coach.gallery_image_3 = request.FILES['gallery_image_3']

        # Clear gallery images if requested
        if request.POST.get('clear_gallery_1'):
            coach.gallery_image_1 = None
        if request.POST.get('clear_gallery_2'):
            coach.gallery_image_2 = None
        if request.POST.get('clear_gallery_3'):
            coach.gallery_image_3 = None

        coach.save()
        messages.success(request, 'Your profile has been updated!')
        return redirect('coaches:edit_profile')

    context = {
        'coach': coach,
    }
    return render(request, 'coaches/edit_profile.html', context)


def coach_public_profile(request, slug):
    """Public coach profile page."""
    coach = get_object_or_404(Coach, slug=slug, is_active=True, profile_enabled=True)

    # Get review stats if available
    from reviews.models import Review
    reviews = Review.objects.filter(coach=coach, is_approved=True).order_by('-created_at')[:5]
    review_stats = Review.objects.filter(coach=coach, is_approved=True).aggregate(
        avg_rating=models.Avg('rating'),
        total_reviews=models.Count('id')
    )

    # Get session count
    total_sessions = Booking.objects.filter(coach=coach, status='completed').count()

    # Parse specializations
    specializations = []
    if coach.specializations:
        specializations = [s.strip() for s in coach.specializations.split(',') if s.strip()]

    context = {
        'coach': coach,
        'reviews': reviews,
        'review_stats': review_stats,
        'total_sessions': total_sessions,
        'specializations': specializations,
    }
    return render(request, 'coaches/public_profile.html', context)
