"""
URL configuration for Atletas World project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


class LoginRequiredTemplateView(LoginRequiredMixin, TemplateView):
    """Template view that requires login."""
    login_url = '/accounts/login/'


@login_required
def login_redirect_view(request):
    """Redirect users to appropriate portal after login based on user groups."""
    # Check if user is in Coach group
    if request.user.groups.filter(name='Coach').exists():
        return redirect('coaches:dashboard')

    # Check if user is in Client group or default to client portal
    # Also create Client profile if it doesn't exist
    if request.user.groups.filter(name='Client').exists() or not request.user.groups.exists():
        from clients.models import Client
        Client.objects.get_or_create(user=request.user)
        return redirect('clients:dashboard')

    # Fallback for admin users
    return redirect('clients:dashboard')


@login_required
def book_redirect_view(request):
    """Redirect to client booking page."""
    return redirect('clients:book')


urlpatterns = [
    # Login redirect
    path('login-redirect/', login_redirect_view, name='login_redirect'),

    # Public pages
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path('about/', TemplateView.as_view(template_name='about.html'), name='about'),
    path('contact/', TemplateView.as_view(template_name='contact.html'), name='contact'),
    path('book/', book_redirect_view, name='book'),  # Redirects to portal booking
    path('comparison/', TemplateView.as_view(template_name='comparison.html'), name='comparison'),

    # Coach profiles
    path('coach/mirko/', TemplateView.as_view(template_name='coach_mirko.html'), name='coach_mirko'),
    path('coach/roger/', TemplateView.as_view(template_name='coach_roger.html'), name='coach_roger'),

    # Admin and auth
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('accounts/', include('allauth.socialaccount.urls')),

    # Client portal pages
    path('portal/', include('clients.urls')),

    # Coach portal pages
    path('coach-portal/', include('coaches.urls')),

    # API endpoints
    path('api/bookings/', include('bookings.urls')),
    path('api/payments/', include('payments.urls')),
    path('api/analytics/', include('analytics.urls')),
    path('api/reviews/', include('reviews.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
