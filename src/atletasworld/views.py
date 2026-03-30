import os
from django.shortcuts import render
from django.http import FileResponse, HttpResponse
from django.conf import settings
from clients.models import Package
from bookings.models import SessionType


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
