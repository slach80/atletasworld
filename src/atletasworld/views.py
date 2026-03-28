from django.shortcuts import render
from clients.models import Package
from bookings.models import SessionType


def home_view(request):
    """Public homepage — packages, events, and programs from the database."""
    packages = Package.objects.filter(is_active=True).order_by('price')
    events = SessionType.objects.filter(show_as_event=True).order_by('start_date', 'name')
    programs = SessionType.objects.filter(is_active=True, show_as_program=True).order_by('name')
    return render(request, 'home.html', {
        'packages': packages,
        'events': events,
        'programs': programs,
    })
