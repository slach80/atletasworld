from django.urls import path
from . import views

app_name = 'coaches'

urlpatterns = [
    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Schedule management
    path('schedule/', views.schedule, name='schedule'),
    path('schedule/add/', views.add_schedule_block, name='add_schedule_block'),
    path('schedule/bulk/', views.add_bulk_schedule, name='add_bulk_schedule'),
    path('schedule/<int:block_id>/delete/', views.delete_schedule_block, name='delete_schedule_block'),

    # Attendance
    path('session/<int:block_id>/attendance/', views.session_attendance, name='session_attendance'),
    path('attendance/<int:attendance_id>/update/', views.update_attendance, name='update_attendance'),

    # Today's sessions
    path('today/', views.todays_sessions, name='todays_sessions'),

    # Assessments
    path('assessments/', views.assessments_list, name='assessments'),
    path('assessments/create/<int:booking_id>/', views.create_assessment, name='create_assessment'),
    path('assessments/quick/<int:block_id>/', views.quick_assess_session, name='quick_assess_session'),

    # My Players
    path('players/', views.my_players, name='my_players'),
    path('players/<int:player_id>/', views.player_detail, name='player_detail'),

    # Notifications
    path('notify/', views.notify_parents, name='notify_parents'),
    path('notify/send/', views.send_notification, name='send_notification'),
]
