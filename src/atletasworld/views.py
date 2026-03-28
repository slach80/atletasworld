from django.shortcuts import render
from clients.models import Package


def home_view(request):
    """Public homepage — passes live packages from the database."""
    packages = Package.objects.filter(is_active=True).order_by('price')
    return render(request, 'home.html', {'packages': packages})
