from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Count, Q
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
    ).select_related('player', 'program')[:10]

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
    """List sessions needing assessment."""
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
    ).select_related('player', 'program').order_by('-scheduled_date')

    # Recent assessments
    recent = PlayerAssessment.objects.filter(
        coach=coach
    ).select_related('player', 'booking__program').order_by('-assessment_date')[:20]

    context = {
        'coach': coach,
        'pending_assessments': pending,
        'recent_assessments': recent,
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
    ).select_related('program').order_by('-scheduled_date')

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
    """Send a notification to a player's parent."""
    coach = request.coach
    from clients.models import Player

    player_id = request.POST.get('player_id')
    notification_type = request.POST.get('notification_type', 'general')
    message = request.POST.get('message', '')

    if player_id and message:
        player = get_object_or_404(Player, id=player_id)
        client = player.client

        # Create notification
        try:
            prefs = client.notification_preferences
            method = prefs.booking_confirmations  # Use their preferred method
        except Exception:
            method = 'email'

        Notification.objects.create(
            client=client,
            notification_type='promotional' if notification_type == 'general' else notification_type.replace('_', '_'),
            title=f'Message from Coach {coach.user.first_name}',
            message=message,
            method=method,
        )

        messages.success(request, f'Notification sent to {client.user.get_full_name()}!')
    else:
        messages.error(request, 'Please provide a message.')

    return redirect('coaches:my_players')
