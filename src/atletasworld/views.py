import os
from django.shortcuts import render
from django.http import FileResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
from django.db.models import Count, Q, Prefetch
from clients.models import Package
from bookings.models import SessionType
from coaches.models import ScheduleBlock
from atletasworld.utils import fmt_times as _fmt_times


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
    return Coach.objects.filter(is_active=True).select_related('user').order_by('display_order', 'user__first_name')


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
    from django.db.models import Sum
    pkg_prefetch = Prefetch(
        'linked_packages',
        queryset=Package.objects.only(
            'id', 'event_start_date', 'event_start_time', 'event_end_date', 'event_end_time'
        ),
    )
    events_qs = SessionType.objects.filter(show_as_event=True).prefetch_related(pkg_prefetch).order_by('event_display_order', 'start_date', 'name')
    today = timezone.localdate()
    programs_qs = SessionType.objects.filter(is_active=True, show_as_program=True).prefetch_related(pkg_prefetch).annotate(
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
        obj.pkg_date = next((p for p in obj.linked_packages.all() if p.event_start_date is not None), None)

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


def adi_view(request):
    """Serve the ADI (Athlete Development Institute) static site at /adi/."""
    path = os.path.join(settings.BASE_DIR, 'static', 'adi', 'index.html')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return HttpResponse(f.read(), content_type='text/html')
    return HttpResponse('<h1>ADI page not found</h1>', status=404)


def tournament_view(request):
    """Kansas City Youth Soccer Tournament 2026 — schedule, groups, bracket."""
    return render(request, 'tournament.html')


def programs_view(request):
    """Special Projects & Events page — APC Select, Serie A, Camps."""
    # Serie A session type IDs for direct booking links
    serie_a = {}
    for st in SessionType.objects.filter(name__icontains='Serie A Elite Scouts'):
        if 'U13' in st.name:
            serie_a['u13_id'] = st.id
        elif 'U19' in st.name:
            serie_a['u19_id'] = st.id

    return render(request, 'programs.html', {
        'serie_a': serie_a,
    })
