from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from datetime import datetime, timedelta
from coaches.models import Coach, ScheduleBlock
from bookings.models import SessionType
from ._auth import coach_required


@coach_required
def schedule(request):
    """View and manage schedule."""
    coach = request.coach
    from django.utils import timezone
    today = timezone.localdate()

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
        'today': today,
        'prev_week': (start_date - timedelta(days=7)).isoformat(),
        'next_week': (start_date + timedelta(days=7)).isoformat(),
        'overlap_warnings': overlap_warnings,
        'session_types': ScheduleBlock.SESSION_TYPE_CHOICES,
        'duration_choices': ScheduleBlock.DURATION_CHOICES,
        'all_session_types': SessionType.objects.filter(is_active=True).order_by('name'),
    }
    return render(request, 'coaches/schedule.html', context)


@coach_required
def add_schedule_block(request):
    """Add a new schedule block."""
    coach = request.coach

    if request.method == 'POST':
        date_str = request.POST.get('date')
        start_time_str = request.POST.get('start_time')
        catalog_id = request.POST.get('catalog_session_type', '').strip()
        duration = int(request.POST.get('duration', 60))
        max_participants = int(request.POST.get('max_participants', 1))

        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_time = datetime.strptime(start_time_str, '%H:%M').time()

            # Resolve catalog session type
            catalog_st = None
            session_type = 'group'
            if catalog_id:
                catalog_st = SessionType.objects.filter(id=catalog_id).first()
                if catalog_st and catalog_st.session_format == 'private':
                    session_type = 'private'
                    max_participants = 1

            # Calculate end time
            start_dt = datetime.combine(date, start_time)
            end_dt = start_dt + timedelta(minutes=duration)
            end_time = end_dt.time()

            location_override = request.POST.get('location_override', '').strip()
            block = ScheduleBlock.objects.create(
                coach=coach,
                date=date,
                start_time=start_time,
                end_time=end_time,
                session_type=session_type,
                duration_minutes=duration,
                max_participants=max_participants,
                location_override=location_override,
            )
            if catalog_ids := request.POST.getlist('catalog_session_type'):
                block.catalog_session_types.set(
                    SessionType.objects.filter(id__in=catalog_ids, is_active=True)
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
        days_of_week = request.POST.getlist('days_of_week')
        start_time_str = request.POST.get('start_time')
        end_time_str = request.POST.get('end_time')
        catalog_ids = request.POST.getlist('catalog_session_type')
        duration = int(request.POST.get('duration', 60))
        max_participants = int(request.POST.get('max_participants', 1))
        location_override = request.POST.get('location_override', '').strip()

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            block_start_time = datetime.strptime(start_time_str, '%H:%M').time()
            block_end_time = datetime.strptime(end_time_str, '%H:%M').time()

            catalog_session_types = list(SessionType.objects.filter(id__in=catalog_ids, is_active=True)) if catalog_ids else []
            session_type = 'group'
            if any(st.session_format == 'private' for st in catalog_session_types):
                session_type = 'private'
                max_participants = 1

            blocks_created = 0
            current_date = start_date

            while current_date <= end_date:
                if str(current_date.weekday()) in days_of_week:
                    current_time = datetime.combine(current_date, block_start_time)
                    day_end = datetime.combine(current_date, block_end_time)

                    while current_time + timedelta(minutes=duration) <= day_end:
                        slot_end = current_time + timedelta(minutes=duration)

                        if not ScheduleBlock.objects.filter(
                            coach=coach,
                            date=current_date,
                            start_time=current_time.time()
                        ).exists():
                            new_block = ScheduleBlock.objects.create(
                                coach=coach,
                                date=current_date,
                                start_time=current_time.time(),
                                end_time=slot_end.time(),
                                session_type=session_type,
                                duration_minutes=duration,
                                max_participants=max_participants,
                                location_override=location_override,
                            )
                            if catalog_session_types:
                                new_block.catalog_session_types.set(catalog_session_types)
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
        'all_session_types': SessionType.objects.filter(is_active=True).order_by('name'),
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
@require_POST
def bulk_delete_blocks(request):
    """Bulk delete schedule blocks by selected IDs or date range."""
    coach = request.coach

    # Mode 1: selected block IDs from weekly view
    block_ids = request.POST.getlist('block_ids')

    # Mode 2: date range filter
    start_date_str = request.POST.get('range_start')
    end_date_str   = request.POST.get('range_end')
    session_type   = request.POST.get('range_session_type', '')

    qs = ScheduleBlock.objects.none()

    if block_ids:
        qs = ScheduleBlock.objects.filter(id__in=block_ids, coach=coach)
    elif start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date   = datetime.strptime(end_date_str,   '%Y-%m-%d').date()
            qs = ScheduleBlock.objects.filter(
                coach=coach, date__gte=start_date, date__lte=end_date
            )
            if session_type:
                qs = qs.filter(session_type=session_type)
        except ValueError:
            messages.error(request, 'Invalid date range.')
            return redirect('coaches:schedule')

    empty   = qs.filter(current_participants=0)
    booked  = qs.filter(current_participants__gt=0)
    deleted = empty.count()
    skipped = booked.count()
    empty.delete()

    if deleted:
        messages.success(request, f'{deleted} block(s) deleted.')
    if skipped:
        messages.warning(request, f'{skipped} block(s) skipped — have active bookings.')
    if not deleted and not skipped:
        messages.info(request, 'No blocks matched.')

    redirect_url = request.POST.get('redirect', '') or 'coaches:schedule'
    try:
        return redirect(redirect_url)
    except Exception:
        return redirect('coaches:schedule')


@coach_required
@require_POST
def bulk_edit_blocks(request):
    """Bulk edit session type, duration, or max participants on selected blocks."""
    coach = request.coach

    block_ids       = request.POST.getlist('block_ids')
    catalog_id      = request.POST.get('session_type', '').strip()  # now sends catalog id
    max_part_str    = request.POST.get('max_participants', '').strip()
    duration_str    = request.POST.get('duration', '').strip()

    if not block_ids:
        messages.error(request, 'No blocks selected.')
        return redirect('coaches:schedule')

    # Resolve catalog session types (modal sends single id via 'session_type' field)
    catalog_ids = [catalog_id] if catalog_id else []
    catalog_session_types = list(SessionType.objects.filter(id__in=catalog_ids, is_active=True))
    new_session_type = ''
    if catalog_session_types:
        new_session_type = 'private' if any(st.session_format == 'private' for st in catalog_session_types) else 'group'

    updated = 0
    skipped = 0
    for bid in block_ids:
        try:
            block = ScheduleBlock.objects.get(id=bid, coach=coach)
            if block.current_participants > 0:
                skipped += 1
                continue
            if catalog_session_types:
                block.catalog_session_types.set(catalog_session_types)
                block.session_type = new_session_type
                if new_session_type == 'private':
                    block.max_participants = 1
            if max_part_str and block.session_type != 'private':
                block.max_participants = int(max_part_str)
            if duration_str:
                dur = int(duration_str)
                block.duration_minutes = dur
                start_dt = datetime.combine(block.date, block.start_time)
                block.end_time = (start_dt + timedelta(minutes=dur)).time()
            block.save()
            updated += 1
        except (ScheduleBlock.DoesNotExist, ValueError):
            pass

    if updated:
        messages.success(request, f'{updated} block(s) updated.')
    if skipped:
        messages.warning(request, f'{skipped} block(s) skipped — have active bookings.')

    redirect_url = request.POST.get('redirect', '') or 'coaches:schedule'
    try:
        return redirect(redirect_url)
    except Exception:
        return redirect('coaches:schedule')
