"""
REST API endpoints for booking calendar integration.
"""
import logging
logger = logging.getLogger(__name__)

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q, Prefetch
from datetime import datetime, timedelta
from decimal import Decimal

from .models import SessionType, AvailabilitySlot, Booking
from coaches.models import Coach, ScheduleBlock
from clients.models import Client, ClientPackage, Package, Player
from clients.services import _location_map_url
from bookings.utils import (
    apply_select_discount,
    get_client_select_membership,
    get_player_select_team_ids,
    is_team_coach,
    notify_pending_payment as _notify_pending_payment,
    SELECT_PICKUP_PRICE,
    SELECT_DISCOUNT_FORMATS,
    SELECT_PICKUP_FORMATS,
)
from bookings.booking_service import BookingError, create_booking

SCHEDULE_BLOCK_CALENDARS = {
    'private': {'id': 'sb_private', 'name': 'Private Training', 'color': '#1a1a1a'},
    'group':   {'id': 'sb_group',   'name': 'Group Training',   'color': '#D7FF00'},
}


class SessionTypeViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for session types."""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = SessionType.objects.filter(is_active=True)
        if not is_team_coach(self.request.user):
            qs = qs.exclude(session_format='team')
        return qs

    def list(self, request):
        queryset = self.get_queryset()
        data = [{
            'id': st.id,
            'name': st.name,
            'description': st.description,
            'session_format': st.session_format,
            'duration_minutes': st.duration_minutes,
            'price': str(st.price),
            'drop_in_price': str(st.get_drop_in_price()),
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
            date__gte=timezone.localdate()
        )

    def list(self, request):
        """Get availability slots for calendar display."""
        queryset = self.get_queryset()
        is_select_member = get_client_select_membership(request.user)

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

        # Eliminate N+1: fetch session_type + coach in one query,
        # prefetch linked_packages filtered once for all slots.
        _pkg_qs = Package.objects.filter(is_active=True, is_purchasable=True).only('id', 'name', 'price')
        queryset = queryset.select_related('session_type', 'coach').prefetch_related(
            Prefetch('session_type__linked_packages', queryset=_pkg_qs)
        )

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
                    'slot_type': 'schedule',
                    'coach_id': slot.coach_id,
                    'coach_name': str(slot.coach),
                    'location_id': getattr(slot, 'location_id', None),
                    'location': slot.session_type.location or '',
                    'location_map_url': _location_map_url(slot.session_type.location or ''),
                    'session_type_id': slot.session_type.id,
                    'session_type_name': slot.session_type.name,
                    'status': slot.status,
                    'spots_remaining': slot.spots_remaining,
                    'max_bookings': slot.max_bookings,
                    'price': str(
                        apply_select_discount(slot.effective_price, slot.session_type.session_format)
                        if is_select_member else slot.effective_price
                    ),
                    'select_discount': is_select_member and apply_select_discount(
                        slot.effective_price, slot.session_type.session_format) is not None,
                    'session_format': slot.session_type.session_format,
                    'allow_package': slot.session_type.allow_package,
                    'requires_package': slot.session_type.requires_package,
                    'drop_in_available': slot.session_type.drop_in_price is not None and slot.session_type.drop_in_price > 0,
                    'linked_packages': [
                        {'id': p.pk, 'name': p.name, 'price': str(p.price)}
                        for p in slot.session_type.linked_packages.all()
                    ],
                    'duration': slot.session_type.duration_minutes,
                }
            })

        # Also include ScheduleBlock records (coach portal schedule)
        sb_queryset = ScheduleBlock.objects.filter(
            status='available'
        ).select_related('coach').prefetch_related(
            Prefetch('catalog_session_types',
                     queryset=SessionType.objects.prefetch_related(
                         Prefetch('linked_packages', queryset=_pkg_qs)
                     ))
        )
        if start_date:
            sb_queryset = sb_queryset.filter(date__gte=start_date)
        if end_date:
            sb_queryset = sb_queryset.filter(date__lte=end_date)
        if coach_id:
            sb_queryset = sb_queryset.filter(coach_id=coach_id)

        team_coach = is_team_coach(request.user)
        is_select_owner_or_coach = request.user.is_staff or request.user.is_superuser or team_coach or request.user.groups.filter(name__in=['Owner', 'Coach']).exists()
        select_team_ids = get_player_select_team_ids(request.user) if is_select_member else []

        for block in sb_queryset:
            cal = SCHEDULE_BLOCK_CALENDARS.get(block.session_type, SCHEDULE_BLOCK_CALENDARS['group'])
            catalog_types = list(block.catalog_session_types.all())

            # --- Select visibility filter ---
            if catalog_types:
                select_formats = {'select_practice', 'select_game'}
                block_formats = {st.session_format for st in catalog_types}
                is_select_block = bool(block_formats & select_formats)
                if is_select_block and not is_select_owner_or_coach:
                    if not is_select_member:
                        continue  # non-Select clients: hide entirely
                    # Select member: show only all-team blocks or blocks for their team(s)
                    if block.select_team_id is not None and block.select_team_id not in select_team_ids:
                        continue  # team-specific block for a different team

            # Skip blocks that are exclusively team session types for non-team-coach clients
            if catalog_types and not team_coach:
                non_team = [st for st in catalog_types if st.session_format != 'team']
                if not non_team:
                    continue  # all types are team-only — hide from regular clients
            if catalog_types:
                name        = ' / '.join(st.name for st in catalog_types)
                color       = catalog_types[0].color if catalog_types[0].color else cal['color']
                base_price  = block.price_override or catalog_types[0].get_drop_in_price()
                sf          = catalog_types[0].session_format
                dur         = catalog_types[0].duration_minutes
                calendar_id = str(catalog_types[0].id)
                type_ids    = [str(st.id) for st in catalog_types]
            else:
                name        = cal['name']
                color       = cal['color']
                base_price  = block.price_override if block.price_override else Decimal('0')
                sf          = block.session_type  # session_type field on ScheduleBlock is a string
                dur         = block.duration_minutes
                calendar_id = cal['id']
                type_ids    = []

            if is_select_member:
                discounted = apply_select_discount(base_price, sf)
                display_price = discounted if discounted is not None else base_price
                has_discount = discounted is not None
            else:
                display_price = base_price
                has_discount = False

            events.append({
                'id': f"sb_{block.id}",
                'calendarId': calendar_id,
                'title': name,
                'category': 'time',
                'start': f"{block.date}T{block.start_time}",
                'end': f"{block.date}T{block.end_time}",
                'backgroundColor': color,
                'borderColor': color,
                'isReadOnly': False,
                'raw': {
                    'slot_id': block.id,
                    'slot_type': 'schedule_block',
                    'coach_id': block.coach_id,
                    'coach_name': str(block.coach),
                    'session_type_name': name,
                    'catalog_type_ids': type_ids,
                    'status': block.status,
                    'spots_remaining': block.spots_remaining,
                    'max_bookings': block.max_participants,
                    'price': str(display_price),
                    'select_discount': has_discount,
                    'session_format': sf,
                    'allow_package': catalog_types[0].allow_package if catalog_types else True,
                    'requires_package': catalog_types[0].requires_package if catalog_types else False,
                    'drop_in_available': (catalog_types[0].drop_in_price is not None and catalog_types[0].drop_in_price > 0) if catalog_types else False,
                    'linked_packages': [
                        {'id': p.pk, 'name': p.name, 'price': str(p.price)}
                        for p in (catalog_types[0].linked_packages.all() if catalog_types else [])
                    ],
                    'duration': dur,
                    'location': block.location_override or (catalog_types[0].location if catalog_types else ''),
                    'location_map_url': _location_map_url(block.location_override or (catalog_types[0].location if catalog_types else '')),
                    'select_team_name': block.select_team.name if block.select_team_id else None,
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
        """Create a new booking. All logic lives in booking_service.create_booking."""
        try:
            result = create_booking(
                user=request.user,
                slot_id=request.data.get('slot_id'),
                slot_type=request.data.get('slot_type', 'availability_slot'),
                player_id=request.data.get('player_id'),
                package_id=request.data.get('package_id'),
                promo_code_str=(request.data.get('promo_code') or '').strip().upper(),
                notes=request.data.get('notes', ''),
            )
            return Response(result, status=status.HTTP_201_CREATED)
        except BookingError as e:
            return Response({'error': e.message, **e.extra}, status=e.status_code)
        except (ScheduleBlock.DoesNotExist, AvailabilitySlot.DoesNotExist) as e:
            return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception('Booking creation failed: slot_id=%s slot_type=%s',
                             request.data.get('slot_id'), request.data.get('slot_type'))
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
            return ClientPackage.objects.filter(
                client=user.client, status='active'
            ).select_related('package')
        return ClientPackage.objects.none()

    def list(self, request):
        """Get client's active packages with remaining sessions."""
        queryset = self.get_queryset().select_related('player')
        data = [{
            'id': pkg.id,
            'package_id': pkg.package_id,
            'package_name': pkg.package.name,
            'player_id': pkg.player_id,
            'player_name': pkg.player.first_name if pkg.player else None,
            'sessions_remaining': pkg.sessions_remaining,
            'sessions_used': pkg.sessions_used,
            'sessions_included': pkg.package.sessions_included,
            'expiry_date': str(pkg.expiry_date),
            'is_valid': pkg.is_valid,
            'can_book': pkg.is_valid and (pkg.package.sessions_included == 0 or pkg.sessions_remaining > 0),
        } for pkg in queryset]

        # Add upgrade options (purchasable, non-team, non-special only)
        available_packages = Package.objects.filter(
            is_active=True, is_purchasable=True, is_special=False
        ).exclude(package_type='team').only('id', 'name', 'price', 'sessions_included').order_by('price')
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
