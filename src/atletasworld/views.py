from django.shortcuts import render
from clients.models import Package
from bookings.models import SessionType


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
    return ' · '.join(results)


def home_view(request):
    """Public homepage — packages, events, and programs from the database."""
    packages = Package.objects.filter(is_active=True).order_by('price')
    events_qs = SessionType.objects.filter(show_as_event=True).prefetch_related('linked_packages').order_by('start_date', 'name')
    programs_qs = SessionType.objects.filter(is_active=True, show_as_program=True).prefetch_related('linked_packages').order_by('name')

    # Annotate formatted start times
    for obj in list(events_qs) + list(programs_qs):
        obj.start_times_fmt = _fmt_times(obj.start_times)

    return render(request, 'home.html', {
        'packages': packages,
        'events': events_qs,
        'programs': programs_qs,
    })
