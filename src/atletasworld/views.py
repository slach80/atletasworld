import os
from django.shortcuts import render
from django.http import FileResponse, HttpResponse
from django.conf import settings
from clients.models import Package
from bookings.models import SessionType
from coaches.models import ScheduleBlock


def apple_pay_verification(request):
    """Serve Apple Pay domain verification file for Stripe.
    Download from: Stripe Dashboard → Settings → Payment methods → Apple Pay → Add domain.
    Place the downloaded file at: static/apple-developer-merchantid-domain-association
    """
    path = os.path.join(settings.BASE_DIR, 'static', 'apple-developer-merchantid-domain-association')
    if os.path.exists(path):
        return FileResponse(open(path, 'rb'), content_type='text/plain')
    return HttpResponse('', content_type='text/plain', status=404)


def _fmt_times(start_times_str):
    """Convert '09:00 10:30' → '9:00 AM · 10:30 AM'"""
    if not start_times_str:
        return ''
    results = []
    for t in start_times_str.split():
        try:
            h, m = map(int, t.split(':'))
            period = 'AM' if h < 12 else 'PM'
            h12 = h % 12 or 12
            results.append(f"{h12}:{m:02d} {period}")
        except Exception:
            results.append(t)
    return ', '.join(results)


def home_view(request):
    """Public homepage — packages, events, and programs from the database."""
    packages = Package.objects.filter(is_active=True).order_by('price')
    events_qs = SessionType.objects.filter(show_as_event=True).prefetch_related('linked_packages').order_by('start_date', 'name')
    programs_qs = SessionType.objects.filter(is_active=True, show_as_program=True).prefetch_related('linked_packages').order_by('name')

    # Annotate formatted start times and a single date range from linked packages
    for obj in list(events_qs) + list(programs_qs):
        obj.start_times_fmt = _fmt_times(obj.start_times)
        obj.weekend_start_times_fmt = _fmt_times(obj.weekend_start_times) if obj.weekend_start_times else ''
        obj.pkg_date = obj.linked_packages.filter(event_start_date__isnull=False).first()

    return render(request, 'home.html', {
        'packages': packages,
        'events': events_qs,
        'programs': programs_qs,
    })


def programs_view(request):
    """Special Projects & Events page — APC Select with live tryout spot counts."""
    import datetime

    TRYOUT_SESSIONS = [
        # (date, label, location, times_display, session_names, is_outdoor)
        (datetime.date(2026, 5, 21), 'Thursday, May 21', 'Atletas Performance Center',
         [('2016s', '6:00 PM'), ('2015s', '7:00 PM'), ('2014s', '8:00 PM')], False),
        (datetime.date(2026, 5, 22), 'Friday, May 22',   'Atletas Performance Center',
         [('2016s', '6:00 PM'), ('2015s', '7:00 PM'), ('2014s', '8:00 PM')], False),
        (datetime.date(2026, 5, 23), 'Saturday, May 23', 'Hocker Grove Middle School',
         [('All Ages', '9:00 AM – 11:00 AM')], True),
        (datetime.date(2026, 5, 24), 'Sunday, May 24',   'Hocker Grove Middle School',
         [('All Ages', '9:00 AM – 11:00 AM')], True),
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
    for date, label, location, slots, is_outdoor in TRYOUT_SESSIONS:
        slots_enriched = []
        for age_label, time_str in slots:
            # Map display time back to 24h for lookup
            time_24 = {
                '6:00 PM': '18:00', '7:00 PM': '19:00', '8:00 PM': '20:00',
                '9:00 AM – 11:00 AM': '09:00',
            }.get(time_str, '00:00')
            bdata = block_map.get((date, time_24), {})
            st_id = bdata.get('session_type_id')
            slots_enriched.append({
                'age_label': age_label,
                'time_str': time_str,
                'spots_remaining': bdata.get('spots_remaining'),
                'max_participants': bdata.get('max_participants'),
                'book_url': f"/book/?st={st_id}" if st_id else "/book/",
            })
        sessions_enriched.append({
            'date': date,
            'label': label,
            'day_num': date.day,
            'location': location,
            'slots': slots_enriched,
            'is_outdoor': is_outdoor,
        })

    return render(request, 'programs.html', {'tryout_sessions': sessions_enriched})
