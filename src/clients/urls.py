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

    # Notifications
    path('notifications/', views.notification_settings, name='notification_settings'),
    path('notifications/history/', views.notification_history, name='notification_history'),
    path('notifications/unread-count/', views.get_unread_count, name='unread_count'),

    # Push notifications API
    path('api/push/subscribe/', views.register_push_subscription, name='push_subscribe'),
    path('api/push/unsubscribe/', views.unregister_push_subscription, name='push_unsubscribe'),

    # Assessments
    path('assessments/', views.assessments_view, name='assessments'),
    path('players/<int:player_id>/assessments/', views.player_assessments, name='player_assessments'),
    path('api/players/<int:player_id>/assessment-data/', views.player_assessment_chart_data, name='player_assessment_data'),
]
