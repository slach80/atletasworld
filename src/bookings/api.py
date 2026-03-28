"""
REST API endpoints for booking calendar integration.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
from datetime import datetime, timedelta
from decimal import Decimal

from .models import SessionType, AvailabilitySlot, Booking
from coaches.models import Coach
from clients.models import Client, ClientPackage


class SessionTypeViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for session types."""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SessionType.objects.filter(is_active=True)

    def list(self, request):
        queryset = self.get_queryset()
        data = [{
            'id': st.id,
            'name': st.name,
            'description': st.description,
            'session_format': st.session_format,
            'duration_minutes': st.duration_minutes,
            'price': str(st.price),
            'max_participants': st.max_participants,
            'color': st.color,
            'requires_package': st.requires_package,
        } for st in queryset]
        return Response(data)


class AvailabilitySlotViewSet(viewsets.ModelViewSet):
    """API endpoint for availability slots (used by coach calendar)."""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        # Check if user is a coach
        if hasattr(user, 'coach'):
            # Coach sees their own slots
            return AvailabilitySlot.objects.filter(coach=user.coach)

        # Clients see all available slots
        return AvailabilitySlot.objects.filter(
            status__in=['available', 'partially_booked'],
            date__gte=timezone.now().date()
        )

    def list(self, request):
        """Get availability slots for calendar display."""
        queryset = self.get_queryset()

        # Date range filtering
        start_date = request.query_params.get('start')
        end_date = request.query_params.get('end')
        coach_id = request.query_params.get('coach_id')

        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        if coach_id:
            queryset = queryset.filter(coach_id=coach_id)

        # Format for Toast UI Calendar
        events = []
        for slot in queryset:
            events.append({
                'id': str(slot.id),
                'calendarId': str(slot.session_type_id),
                'title': f"{slot.session_type.name}",
                'category': 'time',
                'start': f"{slot.date}T{slot.start_time}",
                'end': f"{slot.date}T{slot.end_time}",
                'backgroundColor': slot.session_type.color,
                'borderColor': slot.session_type.color,
                'isReadOnly': slot.status == 'fully_booked',
                'raw': {
                    'slot_id': slot.id,
                    'coach_id': slot.coach_id,
                    'coach_name': str(slot.coach),
                    'session_type_id': slot.session_type_id,
                    'session_type_name': slot.session_type.name,
                    'status': slot.status,
                    'spots_remaining': slot.spots_remaining,
                    'max_bookings': slot.max_bookings,
                    'price': str(slot.effective_price),
                    'duration': slot.session_type.duration_minutes,
                }
            })

        return Response(events)

    def create(self, request):
        """Create a new availability slot (coach only)."""
        user = request.user

        if not hasattr(user, 'coach'):
            return Response({'error': 'Only coaches can create availability slots'},
                          status=status.HTTP_403_FORBIDDEN)

        data = request.data
        try:
            # Parse date/time from Toast UI Calendar format
            start_str = data.get('start', '')
            end_str = data.get('end', '')

            if 'T' in start_str:
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            else:
                start_dt = datetime.fromisoformat(start_str)
                end_dt = datetime.fromisoformat(end_str)

            slot = AvailabilitySlot.objects.create(
                coach=user.coach,
                session_type_id=data.get('calendarId') or data.get('session_type_id'),
                date=start_dt.date(),
                start_time=start_dt.time(),
                end_time=end_dt.time(),
                max_bookings=data.get('max_bookings', 1),
                recurrence=data.get('recurrence', 'none'),
                recurrence_end_date=data.get('recurrence_end_date'),
                notes=data.get('notes', ''),
            )

            # Generate recurring slots if applicable
            if slot.recurrence != 'none' and slot.recurrence_end_date:
                recurring_slots = slot.generate_recurring_slots()
                AvailabilitySlot.objects.bulk_create(recurring_slots)

            return Response({
                'id': str(slot.id),
                'message': 'Availability slot created successfully'
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        """Update an availability slot (coach only)."""
        user = request.user

        try:
            slot = AvailabilitySlot.objects.get(pk=pk, coach=user.coach)
        except AvailabilitySlot.DoesNotExist:
            return Response({'error': 'Slot not found'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data

        # Parse date/time if provided
        if 'start' in data:
            start_str = data['start']
            if 'T' in start_str:
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                slot.date = start_dt.date()
                slot.start_time = start_dt.time()

        if 'end' in data:
            end_str = data['end']
            if 'T' in end_str:
                end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                slot.end_time = end_dt.time()

        if 'calendarId' in data:
            slot.session_type_id = data['calendarId']

        if 'max_bookings' in data:
            slot.max_bookings = data['max_bookings']

        if 'notes' in data:
            slot.notes = data['notes']

        # Check for conflicts before saving
        if slot.check_conflicts():
            return Response({'error': 'This slot conflicts with an existing slot'},
                          status=status.HTTP_400_BAD_REQUEST)

        slot.save()
        return Response({'message': 'Slot updated successfully'})

    def destroy(self, request, pk=None):
        """Delete an availability slot (coach only)."""
        user = request.user

        try:
            slot = AvailabilitySlot.objects.get(pk=pk, coach=user.coach)
        except AvailabilitySlot.DoesNotExist:
            return Response({'error': 'Slot not found'}, status=status.HTTP_404_NOT_FOUND)

        # Check if slot has bookings
        if slot.current_bookings > 0:
            return Response({'error': 'Cannot delete slot with existing bookings'},
                          status=status.HTTP_400_BAD_REQUEST)

        slot.delete()
        return Response({'message': 'Slot deleted successfully'})


class BookingViewSet(viewsets.ModelViewSet):
    """API endpoint for bookings."""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if hasattr(user, 'coach'):
            # Coach sees bookings for their slots
            return Booking.objects.filter(coach=user.coach)

        if hasattr(user, 'client'):
            # Client sees their own bookings
            return Booking.objects.filter(client=user.client)

        return Booking.objects.none()

    def list(self, request):
        """Get bookings for calendar display."""
        queryset = self.get_queryset()

        # Date range filtering
        start_date = request.query_params.get('start')
        end_date = request.query_params.get('end')

        if start_date:
            queryset = queryset.filter(scheduled_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(scheduled_date__lte=end_date)

        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        else:
            queryset = queryset.exclude(status='cancelled')

        # Format for Toast UI Calendar
        events = []
        for booking in queryset:
            end_time = (datetime.combine(booking.scheduled_date, booking.scheduled_time) +
                       timedelta(minutes=booking.duration_minutes)).time()

            events.append({
                'id': f"booking_{booking.id}",
                'calendarId': 'bookings',
                'title': f"{booking.player.first_name if booking.player else 'TBD'} - {booking.session_type.name if booking.session_type else 'Session'}",
                'category': 'time',
                'start': f"{booking.scheduled_date}T{booking.scheduled_time}",
                'end': f"{booking.scheduled_date}T{end_time}",
                'backgroundColor': '#f39c12' if booking.status == 'pending' else '#27ae60',
                'borderColor': '#f39c12' if booking.status == 'pending' else '#27ae60',
                'isReadOnly': True,
                'raw': {
                    'booking_id': booking.id,
                    'client_name': str(booking.client),
                    'player_name': booking.player.first_name if booking.player else 'TBD',
                    'coach_name': str(booking.coach),
                    'status': booking.status,
                    'can_cancel': booking.can_cancel,
                    'can_reschedule': booking.can_reschedule,
                }
            })

        return Response(events)

    def create(self, request):
        """Create a new booking (client only)."""
        user = request.user

        if not hasattr(user, 'client'):
            return Response({'error': 'Only clients can create bookings'},
                          status=status.HTTP_403_FORBIDDEN)

        data = request.data
        client = user.client

        try:
            slot_id = data.get('slot_id')
            player_id = data.get('player_id')
            package_id = data.get('package_id')

            # Get the availability slot
            slot = AvailabilitySlot.objects.get(pk=slot_id)

            # Check availability
            if not slot.is_available:
                return Response({'error': 'This slot is no longer available'},
                              status=status.HTTP_400_BAD_REQUEST)

            # Check package if required
            package = None
            if package_id:
                try:
                    package = ClientPackage.objects.get(pk=package_id, client=client)
                    if package.sessions_remaining <= 0:
                        return Response({
                            'error': 'No sessions remaining in package',
                            'upgrade_available': True,
                            'message': 'Would you like to upgrade your package?'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    if not package.is_valid:
                        return Response({'error': 'Package is expired or inactive'},
                                      status=status.HTTP_400_BAD_REQUEST)
                except ClientPackage.DoesNotExist:
                    return Response({'error': 'Package not found'}, status=status.HTTP_404_NOT_FOUND)

            # Create the booking
            booking = Booking.objects.create(
                client=client,
                player_id=player_id,
                coach=slot.coach,
                availability_slot=slot,
                session_type=slot.session_type,
                scheduled_date=slot.date,
                scheduled_time=slot.start_time,
                duration_minutes=slot.session_type.duration_minutes,
                status='pending',
                client_notes=data.get('notes', ''),
            )

            # Use package if provided
            if package:
                booking.use_package(package)

            # Auto-confirm the booking
            booking.confirm()

            return Response({
                'id': booking.id,
                'message': 'Booking created successfully',
                'booking': {
                    'date': str(booking.scheduled_date),
                    'time': str(booking.scheduled_time),
                    'session_type': booking.session_type.name,
                    'coach': str(booking.coach),
                }
            }, status=status.HTTP_201_CREATED)

        except AvailabilitySlot.DoesNotExist:
            return Response({'error': 'Availability slot not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a booking."""
        user = request.user

        try:
            booking = self.get_queryset().get(pk=pk)
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

        if not booking.can_cancel:
            return Response({'error': 'This booking cannot be cancelled (less than 24 hours notice)'},
                          status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get('reason', 'client_request')
        notes = request.data.get('notes', '')

        try:
            booking.cancel(reason=reason, notes=notes, cancelled_by=user)
            return Response({'message': 'Booking cancelled successfully'})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reschedule(self, request, pk=None):
        """Reschedule a booking to a new slot."""
        user = request.user

        try:
            booking = self.get_queryset().get(pk=pk)
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

        if not booking.can_reschedule:
            return Response({'error': 'This booking cannot be rescheduled'},
                          status=status.HTTP_400_BAD_REQUEST)

        new_slot_id = request.data.get('new_slot_id')
        try:
            new_slot = AvailabilitySlot.objects.get(pk=new_slot_id)
            if not new_slot.is_available:
                return Response({'error': 'New slot is not available'},
                              status=status.HTTP_400_BAD_REQUEST)

            new_booking = booking.reschedule(new_slot, cancelled_by=user)
            return Response({
                'message': 'Booking rescheduled successfully',
                'new_booking_id': new_booking.id
            })
        except AvailabilitySlot.DoesNotExist:
            return Response({'error': 'New slot not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ClientPackageViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for client packages."""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'client'):
            return ClientPackage.objects.filter(client=user.client, status='active')
        return ClientPackage.objects.none()

    def list(self, request):
        """Get client's active packages with remaining sessions."""
        queryset = self.get_queryset()
        data = [{
            'id': pkg.id,
            'package_name': pkg.package.name,
            'sessions_remaining': pkg.sessions_remaining,
            'sessions_used': pkg.sessions_used,
            'expiry_date': str(pkg.expiry_date),
            'is_valid': pkg.is_valid,
            'can_book': pkg.sessions_remaining > 0 and pkg.is_valid,
        } for pkg in queryset]

        # Add upgrade options
        from clients.models import Package
        available_packages = Package.objects.filter(is_active=True).order_by('price')
        upgrades = [{
            'id': pkg.id,
            'name': pkg.name,
            'price': str(pkg.price),
            'sessions_included': pkg.sessions_included,
        } for pkg in available_packages]

        return Response({
            'packages': data,
            'upgrade_options': upgrades
        })
