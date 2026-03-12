from django.urls import path
from . import views

app_name = 'clients'

urlpatterns = [
    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Profile
    path('profile/', views.profile, name='profile'),

    # Players
    path('players/', views.players_list, name='players'),
    path('players/add/', views.player_add, name='player_add'),
    path('players/<int:player_id>/edit/', views.player_edit, name='player_edit'),
    path('players/<int:player_id>/delete/', views.player_delete, name='player_delete'),

    # Packages
    path('packages/', views.packages_list, name='packages'),

    # Bookings
    path('bookings/', views.bookings_list, name='bookings'),
    path('bookings/<int:booking_id>/cancel/', views.booking_cancel, name='booking_cancel'),

    # Book new sessions
    path('book/', views.booking_page, name='book'),
    path('book/reserve/', views.reserve_session, name='reserve_session'),
    path('book/cancel-reservation/', views.cancel_reservation, name='cancel_reservation'),
    path('book/confirm/', views.confirm_booking, name='confirm_booking'),

    # Team Management (for team coaches)
    path('teams/', views.team_list, name='team_list'),
    path('teams/create/', views.team_create, name='team_create'),
    path('teams/<int:team_id>/', views.team_detail, name='team_detail'),
    path('teams/<int:team_id>/edit/', views.team_edit, name='team_edit'),
    path('teams/<int:team_id>/players/add/', views.team_player_add, name='team_player_add'),
    path('teams/<int:team_id>/players/<int:player_id>/remove/', views.team_player_remove, name='team_player_remove'),
    
    # Team Booking
    path('teams/<int:team_id>/book/', views.team_booking_page, name='team_book'),
    path('teams/<int:team_id>/book/reserve/', views.team_reserve_session, name='team_reserve_session'),
    path('teams/<int:team_id>/book/confirm/', views.team_confirm_booking, name='team_confirm_booking'),
    path('team-bookings/', views.team_bookings_list, name='team_bookings'),

    # Notifications
    path('notifications/', views.notification_settings, name='notification_settings'),
    path('notifications/history/', views.notification_history, name='notification_history'),
    path('notifications/unread-count/', views.get_unread_count, name='unread_count'),

    # Push notifications API
    path('api/push/subscribe/', views.register_push_subscription, name='push_subscribe'),
    path('api/push/unsubscribe/', views.unregister_push_subscription, name='push_unsubscribe'),

    # Field Rental
    path('field-rental/', views.field_rental_list, name='field_rental_list'),
    path('field-rental/<int:slot_id>/request/', views.field_rental_request, name='field_rental_request'),
    path('field-rental/<int:slot_id>/cancel/', views.field_rental_cancel, name='field_rental_cancel'),
    path('api/field-rental/available/', views.field_rental_available_json, name='field_rental_available'),

    # Assessments
    path('assessments/', views.assessments_view, name='assessments'),
    path('players/<int:player_id>/assessments/', views.player_assessments, name='player_assessments'),
    path('api/players/<int:player_id>/assessment-data/', views.player_assessment_chart_data, name='player_assessment_data'),
]
