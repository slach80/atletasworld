from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('webhook/', views.payments_webhook, name='webhook'),
    path('booking/<int:booking_id>/pay/', views.create_booking_payment_intent, name='booking_pay'),
]
