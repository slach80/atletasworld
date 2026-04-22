import os
from django.shortcuts import render
from django.http import FileResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
from django.db.models import Count, Q
from clients.models import Package
from bookings.models import SessionType
from coaches.models import ScheduleBlock
from atletasworld.utils import fmt_times as _fmt_times, tryout_label as _tryout_label


def apple_pay_verification(request):
    """Serve Apple Pay domain verification file for Stripe.
    Download from: Stripe Dashboard → Settings → Payment methods → Apple Pay → Add domain.
    Place the downloaded file at: static/apple-developer-merchantid-domain-association
    """
    path = os.path.join(settings.BASE_DIR, 'static', 'apple-developer-merchantid-domain-association')
    if os.path.exists(path):
        return FileResponse(open(path, 'rb'), content_type='text/plain')
    return HttpResponse('', content_type='text/plain', status=404)


def _get_active_coaches():
    from coaches.models import Coach
    return Coach.objects.filter(is_active=True).select_related('user').order_by('user__first_name')


def about_view(request):
    return render(request, 'about.html', {'active_coaches': _get_active_coaches()})


def home_view(request):
    """Public homepage — packages, events, and programs from the database."""
    active_coaches = _get_active_coaches()
    raw_sessions = sum(c.sessions_display_floor for c in active_coaches)
    total_sessions_rounded = round(raw_sessions / 100) * 100 if raw_sessions else 0

    packages = Package.objects.filter(
        is_active=True, is_purchasable=True, is_special=False
    ).exclude(package_type__in=['select', 'team']).order_by('price')
    events_qs = SessionType.objects.filter(show_as_event=True).prefetch_related('linked_packages').order_by('event_display_order', 'start_date', 'name')
    from django.db.models import Sum
    today = timezone.localdate()
    programs_qs = SessionType.objects.filter(is_active=True, show_as_program=True).prefetch_related('linked_packages').annotate(
        confirmed_bookings=Count(
            'bookings',
            filter=Q(bookings__status__in=['pending', 'confirmed'],
                     bookings__scheduled_date__gte=today),
            distinct=True,
        ),
    ).order_by('name')

    # Compute total block capacity per session type in one query to avoid
    # ORM JOIN multiplication (two M2M annotates inflate each other's counts).
    block_caps = (
        ScheduleBlock.objects
        .filter(date__gte=today, status__in=['available', 'booked'])
        .values('catalog_session_types')
        .annotate(total=Sum('max_participants'))
    )
    cap_by_st = {row['catalog_session_types']: row['total'] for row in block_caps}

    # Annotate formatted start times and a single date range from linked packages
    for obj in list(events_qs) + list(programs_qs):
        obj.start_times_fmt = _fmt_times(obj.start_times)
        obj.weekend_start_times_fmt = _fmt_times(obj.weekend_start_times) if obj.weekend_start_times else ''
        obj.pkg_date = obj.linked_packages.filter(event_start_date__isnull=False).first()

    for obj in programs_qs:
        cap = cap_by_st.get(obj.pk)
        # Only surface block-based capacity for date-bounded sessions (camp/clinic).
        # For open-ended recurring programs, the sum across all future blocks is
        # meaningless (e.g. 5150 for a summer program running all summer).
        obj.total_block_capacity = cap if (cap and obj.start_date and obj.end_date) else None

    return render(request, 'home.html', {
        'packages': packages,
        'events': events_qs,
        'programs': programs_qs,
        'active_coaches': active_coaches,
        'total_sessions_rounded': total_sessions_rounded,
    })


def programs_view(request):
    """Special Projects & Events page — APC Select with live tryout spot counts."""
    import datetime

    TRYOUT_SESSIONS = [
        # (date, location, slots, is_outdoor)
        (datetime.date(2026, 5, 21), 'Atletas Performance Center',
         [('2016s', '6:00 PM', '18:00'), ('2015s', '7:00 PM', '19:00'), ('2014s', '8:00 PM', '20:00')], False),
        (datetime.date(2026, 5, 22), 'Atletas Performance Center',
         [('2016s', '7:00 PM', '19:00'), ('2015s', '8:00 PM', '20:00'), ('2014s', '9:00 PM', '21:00')], False),
        (datetime.date(2026, 5, 23), 'Hocker Grove Middle School',
         [('All Ages', '9:00 AM – 11:00 AM', '09:00')], True),
        (datetime.date(2026, 5, 24), 'Indian Woods Middle School',
         [('All Ages', '9:00 AM – 11:00 AM', '09:00')], True),
    ]

    # Build a map: (date, start_time) -> {spots_remaining, max_participants, session_type_id}
    tryout_blocks = ScheduleBlock.objects.filter(
        date__in=[s[0] for s in TRYOUT_SESSIONS],
        status='available',
    ).prefetch_related('catalog_session_types')

    block_map = {}
    for b in tryout_blocks:
        cat = list(b.catalog_session_types.all())
        block_map[(b.date, b.start_time.strftime('%H:%M'))] = {
            'spots_remaining': b.spots_remaining,
            'max_participants': b.max_participants,
            'session_type_id': cat[0].id if cat else None,
        }

    # Enrich TRYOUT_SESSIONS with spot data
    sessions_enriched = []
    for date, location, slots, is_outdoor in TRYOUT_SESSIONS:
        slots_enriched = []
        for age_label, time_str, time_24 in slots:
            bdata = block_map.get((date, time_24), {})
            st_id = bdata.get('session_type_id')
            spots_remaining = bdata.get('spots_remaining')
            max_participants = bdata.get('max_participants')
            registered = (max_participants - spots_remaining) if (spots_remaining is not None and max_participants) else None
            slots_enriched.append({
                'age_label': age_label,
                'time_str': time_str,
                'spots_remaining': spots_remaining,
                'max_participants': max_participants,
                'registered': registered,
                'book_url': f"/book/?st={st_id}" if st_id else "/book/",
            })
        sessions_enriched.append({
            'date': date,
            'label': _tryout_label(date),
            'day_num': date.day,
            'location': location,
            'slots': slots_enriched,
            'is_outdoor': is_outdoor,
        })

    # Serie A session type IDs for direct booking links
    serie_a = {}
    for st in SessionType.objects.filter(name__icontains='Serie A Elite Scouts'):
        if 'U13' in st.name:
            serie_a['u13_id'] = st.id
        elif 'U19' in st.name:
            serie_a['u19_id'] = st.id

    return render(request, 'programs.html', {
        'tryout_sessions': sessions_enriched,
        'serie_a': serie_a,
    })
