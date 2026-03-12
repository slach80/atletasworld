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
from .admin_views import (
    owner_dashboard, owner_notifications, owner_send_notification,
    owner_packages, owner_package_add, owner_package_edit, owner_package_delete,
    owner_coaches, owner_coach_add, owner_coach_edit, owner_coach_delete, owner_coach_schedule,
    owner_bookings, owner_booking_detail,
    owner_clients, owner_client_detail, owner_players,
    owner_session_types, owner_session_type_edit,
    owner_teams, owner_team_detail,
    owner_field_slots, owner_field_slot_edit,
    owner_field_slot_approve, owner_field_slot_reject,
    owner_field_slot_cancel, owner_field_slot_conflict_check,
)


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
    # Check if user is in Owner group - redirect to owner dashboard
    if request.user.groups.filter(name='Owner').exists():
        return redirect('owner_dashboard')

    # Check if user is in Coach group
    if request.user.groups.filter(name='Coach').exists():
        return redirect('coaches:dashboard')

    # Check if user is in Client group or default to client portal
    # Also create Client profile if it doesn't exist
    if request.user.groups.filter(name='Client').exists() or not request.user.groups.exists():
        from clients.models import Client
        Client.objects.get_or_create(user=request.user)
        return redirect('clients:dashboard')

    # Fallback for staff/superuser - redirect to Django admin
    if request.user.is_staff or request.user.is_superuser:
        return redirect('/admin/')

    # Default fallback to client dashboard
    return redirect('clients:dashboard')


@login_required
def book_redirect_view(request):
    """Redirect to client booking page."""
    return redirect('clients:book')


urlpatterns = [
    # Login redirect
    path('login-redirect/', login_redirect_view, name='login_redirect'),

    # Owner dashboard (custom, not Django admin)
    path('owner-portal/', owner_dashboard, name='owner_dashboard'),
    path('owner-portal/notifications/', owner_notifications, name='owner_notifications'),
    path('owner-portal/notifications/send/', owner_send_notification, name='owner_send_notification'),

    # Owner - Package Management
    path('owner-portal/packages/', owner_packages, name='owner_packages'),
    path('owner-portal/packages/add/', owner_package_add, name='owner_package_add'),
    path('owner-portal/packages/<int:pk>/edit/', owner_package_edit, name='owner_package_edit'),
    path('owner-portal/packages/<int:pk>/delete/', owner_package_delete, name='owner_package_delete'),

    # Owner - Coach Management
    path('owner-portal/coaches/', owner_coaches, name='owner_coaches'),
    path('owner-portal/coaches/add/', owner_coach_add, name='owner_coach_add'),
    path('owner-portal/coaches/<int:pk>/edit/', owner_coach_edit, name='owner_coach_edit'),
    path('owner-portal/coaches/<int:pk>/delete/', owner_coach_delete, name='owner_coach_delete'),
    path('owner-portal/coaches/<int:pk>/schedule/', owner_coach_schedule, name='owner_coach_schedule'),

    # Owner - Booking Management
    path('owner-portal/bookings/', owner_bookings, name='owner_bookings'),
    path('owner-portal/bookings/<int:pk>/', owner_booking_detail, name='owner_booking_detail'),

    # Owner - Client/Player Management
    path('owner-portal/clients/', owner_clients, name='owner_clients'),
    path('owner-portal/clients/<int:pk>/', owner_client_detail, name='owner_client_detail'),
    path('owner-portal/players/', owner_players, name='owner_players'),

    # Owner - Session Types
    path('owner-portal/session-types/', owner_session_types, name='owner_session_types'),
    path('owner-portal/session-types/<int:pk>/edit/', owner_session_type_edit, name='owner_session_type_edit'),

    # Owner - Team Management
    path('owner-portal/teams/', owner_teams, name='owner_teams'),
    path('owner-portal/teams/<int:pk>/', owner_team_detail, name='owner_team_detail'),

    # Owner - Field Rental Management
    path('owner-portal/field-rental/', owner_field_slots, name='owner_field_slots'),
    path('owner-portal/field-rental/conflict-check/', owner_field_slot_conflict_check, name='owner_field_slot_conflict_check'),
    path('owner-portal/field-rental/<int:pk>/edit/', owner_field_slot_edit, name='owner_field_slot_edit'),
    path('owner-portal/field-rental/<int:pk>/approve/', owner_field_slot_approve, name='owner_field_slot_approve'),
    path('owner-portal/field-rental/<int:pk>/reject/', owner_field_slot_reject, name='owner_field_slot_reject'),
    path('owner-portal/field-rental/<int:pk>/cancel/', owner_field_slot_cancel, name='owner_field_slot_cancel'),

    # Theme preview (temporary)
    path('preview-gymlife/', gymlife_preview, name='gymlife_preview'),

    # Public pages
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path('about/', TemplateView.as_view(template_name='about.html'), name='about'),
    path('contact/', TemplateView.as_view(template_name='contact.html'), name='contact'),
    path('book/', book_redirect_view, name='book'),  # Redirects to portal booking
    path('comparison/', TemplateView.as_view(template_name='comparison.html'), name='comparison'),

    # Coach public profiles - static templates for main coaches (must be before dynamic route)
    path('coach/mirko/', TemplateView.as_view(template_name='coach_mirko.html'), name='coach_mirko'),
    path('coach/roger/', TemplateView.as_view(template_name='coach_roger.html'), name='coach_roger'),

    # Coach public profiles (dynamic based on slug - fallback for other coaches)
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
