"""
Client portal VALD performance URLs.
"""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.player_performance, name='performance'),
    path('player/<int:player_id>/', views.player_detail, name='performance_detail'),
]
