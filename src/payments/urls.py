from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('webhook/', views.payments_webhook, name='webhook'),
]
