from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api import SessionTypeViewSet, AvailabilitySlotViewSet, BookingViewSet, ClientPackageViewSet

app_name = 'bookings'

router = DefaultRouter()
router.register(r'session-types', SessionTypeViewSet, basename='sessiontype')
router.register(r'availability', AvailabilitySlotViewSet, basename='availability')
router.register(r'bookings', BookingViewSet, basename='booking')
router.register(r'packages', ClientPackageViewSet, basename='package')

urlpatterns = [
    path('', include(router.urls)),
]
