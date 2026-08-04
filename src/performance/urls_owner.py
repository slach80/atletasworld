"""
Owner portal VALD performance URLs.

Separate from admin_views.py to keep god-object discipline.
"""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.owner_performance, name='owner_performance'),
    path('player/<int:player_id>/', views.owner_player_detail, name='owner_performance_detail'),
    path('sync/', views.owner_trigger_sync, name='owner_vald_sync'),
    path('match/<int:player_id>/', views.owner_match_profile, name='owner_vald_match'),
]
