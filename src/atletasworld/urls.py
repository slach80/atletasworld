"""
URL configuration for Atletas World project.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from coaches.views import coach_public_profile


def gymlife_preview(request):
    """Preview the gymlife theme with current data."""
    from coaches.models import Coach
    from bookings.models import SessionType
    from reviews.models import Review

    coaches = Coach.objects.filter(is_active=True, profile_enabled=True)
    session_types = SessionType.objects.filter(is_active=True)[:5]
    reviews = Review.objects.filter(is_approved=True, is_featured=True)[:5]

    return render(request, 'gymlife_preview.html', {
        'coaches': coaches,
        'session_types': session_types,
        'reviews': reviews,
    })


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

    # Theme preview (temporary)
    path('preview-gymlife/', gymlife_preview, name='gymlife_preview'),

    # Public pages
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path('about/', TemplateView.as_view(template_name='about.html'), name='about'),
    path('contact/', TemplateView.as_view(template_name='contact.html'), name='contact'),
    path('book/', book_redirect_view, name='book'),  # Redirects to portal booking
    path('comparison/', TemplateView.as_view(template_name='comparison.html'), name='comparison'),

    # Coach public profiles (dynamic based on slug)
    path('coach/<slug:slug>/', coach_public_profile, name='coach_public_profile'),

    # Grappelli admin (must be before admin)
    path('grappelli/', include('grappelli.urls')),

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
