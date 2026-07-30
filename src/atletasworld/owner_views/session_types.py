from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Count
from django.views.decorators.http import require_POST
from bookings.models import SessionType, Booking
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_session_type_hard_delete(request, pk):
    """Permanently delete a session type (only if no bookings reference it)."""
    from bookings.models import SessionType, Booking
    from django.shortcuts import get_object_or_404

    st = get_object_or_404(SessionType, pk=pk)
    booking_count = Booking.objects.filter(session_type=st).count()
    if booking_count > 0:
        messages.error(request, f'Cannot delete "{st.name}" — {booking_count} booking(s) reference it. Archive it instead.')
    else:
        name = st.name
        st.delete()
        messages.success(request, f'Session type "{name}" permanently deleted.')
    return redirect('owner_session_types')


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_session_type_duplicate(request, pk):
    """Duplicate a session type."""
    from bookings.models import SessionType
    from django.shortcuts import get_object_or_404

    orig = get_object_or_404(SessionType, pk=pk)
    copy = SessionType.objects.create(
        name=f'{orig.name} (Copy)',
        description=orig.description,
        session_format=orig.session_format,
        duration_minutes=orig.duration_minutes,
        price=orig.price,
        drop_in_price=orig.drop_in_price,
        max_participants=orig.max_participants,
        color=orig.color,
        is_active=False,  # start archived
        requires_package=orig.requires_package,
        show_as_event=False,
        show_as_program=False,
        location=orig.location,
        age_group=orig.age_group,
        days_of_week=orig.days_of_week,
        start_times=orig.start_times,
        weekend_start_times=orig.weekend_start_times,
    )
    messages.success(request, f'Session type duplicated as "{copy.name}". Review and activate when ready.')
    return redirect('owner_session_type_edit', pk=copy.pk)


@login_required
@user_passes_test(is_owner)
def owner_session_types(request):
    """Manage session types."""
    base_st = SessionType.objects.annotate(total_bookings=Count('bookings'))
    session_types          = base_st.filter(is_active=True).order_by('name')
    archived_session_types = base_st.filter(is_active=False).order_by('name')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            try:
                st = SessionType.objects.create(
                    name=request.POST.get('name'),
                    description=request.POST.get('description', ''),
                    session_format=request.POST.get('session_format', 'private'),
                    duration_minutes=request.POST.get('duration_minutes', 60),
                    price=request.POST.get('price'),
                    max_participants=request.POST.get('max_participants', 1),
                    color=request.POST.get('color', '#2ecc71'),
                    is_active=request.POST.get('is_active') == 'on',
                    requires_package=request.POST.get('requires_package') == 'on',
                    allow_package=request.POST.get('allow_package') == 'on',
                    show_as_event=request.POST.get('show_as_event') == 'on',
                    show_as_program=request.POST.get('show_as_program') == 'on',
                    start_times=' '.join(t for t in request.POST.getlist('start_times') if t),
                    location=request.POST.get('location', ''),
                    age_group=request.POST.get('age_group', ''),
                    days_of_week=','.join(request.POST.getlist('days_of_week')),
                    # Clinic/Camp fields
                    start_date=request.POST.get('start_date') or None,
                    end_date=request.POST.get('end_date') or None,
                    min_age=request.POST.get('min_age') or None,
                    max_age=request.POST.get('max_age') or None,
                )
                pkg_ids = request.POST.getlist('linked_packages')
                if pkg_ids:
                    from clients.models import Package as Pkg
                    st.linked_packages.set(Pkg.objects.filter(pk__in=pkg_ids))
                messages.success(request, 'Session type created!')
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')

        elif action == 'toggle':
            st_id = request.POST.get('session_type_id')
            try:
                st = SessionType.objects.get(pk=st_id)
                st.is_active = not st.is_active
                st.save()
                messages.success(request, f'Session type {"activated" if st.is_active else "deactivated"}.')
            except SessionType.DoesNotExist:
                messages.error(request, 'Session type not found.')

        return redirect('owner_session_types')

    from clients.models import Package
    context = {
        'session_types': session_types,
        'archived_session_types': archived_session_types,
        'format_choices': SessionType.SESSION_FORMAT_CHOICES,
        'days_of_week_choices': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'packages': Package.objects.filter(is_active=True).order_by('name'),
        'archived_linked_packages': [],
        'linked_package_ids': [],
    }
    return render(request, 'owner/session_types.html', context)


@login_required
@user_passes_test(is_owner)
def owner_session_type_edit(request, pk):
    """Edit a session type."""
    from django.shortcuts import get_object_or_404

    session_type = get_object_or_404(SessionType, pk=pk)

    if request.method == 'POST':
        try:
            session_type.name = request.POST.get('name')
            session_type.description = request.POST.get('description', '')
            session_type.session_format = request.POST.get('session_format', 'private')
            session_type.duration_minutes = request.POST.get('duration_minutes', 60)
            session_type.price = request.POST.get('price')
            drop_in = request.POST.get('drop_in_price', '').strip()
            session_type.drop_in_price = drop_in if drop_in else None
            session_type.max_participants = request.POST.get('max_participants', 1)
            session_type.color = request.POST.get('color', '#2ecc71')
            session_type.is_active = request.POST.get('is_active') == 'on'
            session_type.requires_package = request.POST.get('requires_package') == 'on'
            session_type.allow_package    = request.POST.get('allow_package') == 'on'
            session_type.show_as_event = request.POST.get('show_as_event') == 'on'
            session_type.show_as_program = request.POST.get('show_as_program') == 'on'
            # Poster image
            if request.POST.get('clear_poster_image') and session_type.poster_image:
                session_type.poster_image.delete(save=False)
                session_type.poster_image = None
            elif 'poster_image' in request.FILES:
                new_poster = request.FILES['poster_image']
                from clients.utils import validate_photo
                err = validate_photo(new_poster)
                if err:
                    raise ValueError(err)
                if session_type.poster_image:
                    session_type.poster_image.delete(save=False)
                session_type.poster_image = new_poster
            # Carousel CTA + order
            session_type.event_cta_text = request.POST.get('event_cta_text', '').strip()
            session_type.event_cta_url = request.POST.get('event_cta_url', '').strip()
            try:
                session_type.event_display_order = int(request.POST.get('event_display_order', 0))
            except (ValueError, TypeError):
                session_type.event_display_order = 0
            session_type.start_times = ' '.join(t for t in request.POST.getlist('start_times') if t)
            session_type.weekend_start_times = ' '.join(t for t in request.POST.getlist('weekend_start_times') if t)
            session_type.location = request.POST.get('location', '')
            session_type.age_group = request.POST.get('age_group', '')
            session_type.days_of_week = ','.join(request.POST.getlist('days_of_week'))
            # Clinic/Camp fields
            session_type.start_date = request.POST.get('start_date') or None
            session_type.end_date = request.POST.get('end_date') or None
            session_type.min_age = request.POST.get('min_age') or None
            session_type.max_age = request.POST.get('max_age') or None
            # Per-day/time capacity rules: fields named cap_<Day>_<HH:MM>
            day_capacities = {}
            for key, val in request.POST.items():
                if key.startswith('cap_') and val.strip():
                    try:
                        day_capacities[key[4:]] = int(val)
                    except ValueError:
                        pass
            session_type.day_capacities = day_capacities
            session_type.save()
            pkg_ids = request.POST.getlist('linked_packages')
            from clients.models import Package as Pkg
            session_type.linked_packages.set(Pkg.objects.filter(pk__in=pkg_ids))
            messages.success(request, f'Session type "{session_type.name}" updated!')
            return redirect('owner_session_types')
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')

    from clients.models import Package as Pkg
    linked_ids = list(session_type.linked_packages.values_list('pk', flat=True))
    # Purchasable active packages shown in selector
    purchasable_pkgs = Pkg.objects.filter(is_active=True, is_purchasable=True).order_by('name')
    # Also show active-but-not-purchasable (e.g. spring packages) in selector — clients may still hold them
    active_pkgs = Pkg.objects.filter(is_active=True).order_by('name')
    # Archived packages already linked → shown as read-only (preserve link)
    archived_linked = Pkg.objects.filter(pk__in=linked_ids, is_active=False)
    context = {
        'session_type': session_type,
        'format_choices': SessionType.SESSION_FORMAT_CHOICES,
        'packages': active_pkgs,
        'archived_linked_packages': archived_linked,
        'linked_package_ids': linked_ids,
        'days_of_week_choices': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    }
    return render(request, 'owner/session_type_form.html', context)


@login_required
@user_passes_test(is_owner)
def owner_session_type_apply_capacities(request, pk):
    """AJAX: bulk-update ScheduleBlock.max_participants for blocks linked to this session type."""
    import json
    from django.http import JsonResponse
    from django.shortcuts import get_object_or_404
    from coaches.models import ScheduleBlock

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    session_type = get_object_or_404(SessionType, pk=pk)

    try:
        data = json.loads(request.body)
        capacities = data.get('capacities', {})  # {"Mon_17:00": 20, ...}
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not capacities:
        return JsonResponse({'error': 'No capacity rules provided'}, status=400)

    # Day abbr → weekday integer (Monday=0)
    day_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}

    blocks = ScheduleBlock.objects.filter(catalog_session_types=session_type)
    updated = 0

    for block in blocks:
        day_abbr = list(day_map.keys())[block.date.weekday()]
        time_str = block.start_time.strftime('%H:%M')
        key = f"{day_abbr}_{time_str}"
        if key in capacities:
            new_cap = int(capacities[key])
            if block.max_participants != new_cap:
                block.max_participants = new_cap
                block.save(update_fields=['max_participants'])
                updated += 1

    # Also save capacities to the session type
    session_type.day_capacities = {k: int(v) for k, v in capacities.items()}
    session_type.save(update_fields=['day_capacities'])

    return JsonResponse({'updated': updated})


@login_required
@user_passes_test(is_owner)
def owner_session_type_roster(request, pk):
    """Capacity roster: bookings vs max per day/time for a session type."""
    from django.shortcuts import get_object_or_404
    from coaches.models import ScheduleBlock
    from django.db.models import Count, Q

    session_type = get_object_or_404(SessionType, pk=pk)

    # All schedule blocks linked to this session type
    blocks = (
        ScheduleBlock.objects
        .filter(catalog_session_types=session_type)
        .select_related('coach__user')
        .order_by('date', 'start_time')
    )

    # Pre-fetch booking counts keyed by (coach_id, date, start_time)
    booking_counts = {}
    for b in (
        Booking.objects
        .filter(session_type=session_type, status__in=['pending', 'confirmed'])
        .values('coach_id', 'scheduled_date', 'scheduled_time')
        .annotate(cnt=Count('id'))
    ):
        booking_counts[(b['coach_id'], b['scheduled_date'], b['scheduled_time'])] = b['cnt']

    # Build roster rows with fill metrics
    roster = []
    for block in blocks:
        booked = booking_counts.get(
            (block.coach_id, block.date, block.start_time), 0
        )
        capacity = session_type.get_capacity(
            ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][block.date.weekday()],
            block.start_time.strftime('%H:%M'),
        )
        pct = round(booked / capacity * 100) if capacity else 0
        roster.append({
            'block':    block,
            'booked':   booked,
            'capacity': capacity,
            'pct':      pct,
            'status':   'full' if pct >= 100 else ('warning' if pct >= 70 else 'ok'),
        })

    context = {
        'session_type': session_type,
        'roster':       roster,
        'total_booked': sum(r['booked'] for r in roster),
        'total_capacity': sum(r['capacity'] for r in roster),
    }
    return render(request, 'owner/session_type_roster.html', context)
