from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from coaches.models import Coach, ScheduleBlock, SessionAttendance
from bookings.models import Booking
from ._auth import coach_required


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
    today = timezone.localdate()

    import datetime as dt
    from collections import defaultdict

    # Single query for blocks + prefetch M2M catalog_session_types
    blocks = ScheduleBlock.objects.filter(
        coach=coach,
        date=today
    ).order_by('start_time').prefetch_related('catalog_session_types')

    # Single query for ALL today's bookings, grouped by start_time in Python
    all_bookings = Booking.objects.filter(
        coach=coach,
        scheduled_date=today,
        status__in=['pending', 'confirmed']
    ).select_related('player', 'client')
    bookings_by_time = defaultdict(list)
    for b in all_bookings:
        bookings_by_time[b.scheduled_time].append(b)

    now_dt = timezone.now()
    blocks_with_players = []
    for block in blocks:
        # Minutes until start
        block_dt = dt.datetime.combine(today, block.start_time)
        block_dt = timezone.make_aware(block_dt) if timezone.is_naive(block_dt) else block_dt
        mins_until = int((block_dt - now_dt).total_seconds() / 60)

        # Location from prefetched catalog_session_types (no extra query)
        location = ''
        catalog_types = block.catalog_session_types.all()
        if catalog_types and catalog_types[0].location:
            location = catalog_types[0].location

        blocks_with_players.append({
            'block': block,
            'bookings': bookings_by_time[block.start_time],
            'mins_until': mins_until,
            'location': location,
        })

    context = {
        'coach': coach,
        'today': today,
        'blocks_with_players': blocks_with_players,
    }
    return render(request, 'coaches/todays_sessions.html', context)
