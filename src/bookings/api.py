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
from django.db.models import Q
from datetime import datetime, timedelta
from decimal import Decimal

from .models import SessionType, AvailabilitySlot, Booking
from coaches.models import Coach, ScheduleBlock
from clients.models import Client, ClientPackage

SCHEDULE_BLOCK_CALENDARS = {
    'private': {'id': 'sb_private', 'name': 'Private Training', 'color': '#1a1a1a'},
    'group':   {'id': 'sb_group',   'name': 'Group Training',   'color': '#D7FF00'},
}


SELECT_PICKUP_PRICE = Decimal('5.00')
SELECT_DISCOUNT_FORMATS = {'camp', 'clinic'}   # 10% off
SELECT_PICKUP_FORMATS = {'pickup'}              # flat $5


def apply_select_discount(price, session_format):
    """Return discounted price for APC Select members, or None if no discount applies."""
    if session_format in SELECT_PICKUP_FORMATS:
        return SELECT_PICKUP_PRICE
    if session_format in SELECT_DISCOUNT_FORMATS:
        return (price * Decimal('0.90')).quantize(Decimal('0.01'))
    return None


def get_client_select_membership(user):
    """Return True if user has an active APC Select ClientPackage."""
    if not user.is_authenticated or not hasattr(user, 'client'):
        return False
    today = timezone.now().date()
    return user.client.packages.filter(
        package__package_type='select',
        status='active',
        expiry_date__gte=today,
    ).exists()


def _notify_pending_payment(booking, amount_due):
    """Notify coach and owners when a drop-in booking is pending payment."""
    try:
        from clients.models import Client, Notification
        from django.contrib.auth.models import User
        player_name = str(booking.player) if booking.player else booking.client.user.get_full_name()
        session_name = booking.session_type.name if booking.session_type else 'Session'
        date_str = booking.scheduled_date.strftime('%b %-d') if booking.scheduled_date else ''
        msg = (f"{player_name} reserved {session_name} on {date_str} "
               f"— awaiting payment of ${amount_due:.2f}. Session held for 24 hours.")
        # Coach notification
        if booking.coach and hasattr(booking.coach, 'user'):
            if hasattr(booking.coach.user, 'client'):
                Notification.objects.create(
                    client=booking.coach.user.client,
                    notification_type='promotional',
                    title=f'Pending Payment: {player_name}',
                    message=msg, method='in_app',
                )
        # Owner notification
        for owner in User.objects.filter(groups__name='Owner'):
            if hasattr(owner, 'client'):
                Notification.objects.create(
                    client=owner.client,
                    notification_type='promotional',
                    title=f'Pending Payment: {session_name} — ${amount_due:.2f}',
                    message=msg, method='in_app',
                )
    except Exception:
        pass  # never block a booking due to notification failure


def is_team_coach(user):
    """Team coaches/managers see team session types; regular parents don't."""
    if hasattr(user, 'coach'):
        return True
    if hasattr(user, 'client') and user.client.client_type == 'coach':
        return True
    return False


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
            date__gte=timezone.now().date()
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
                        for p in slot.session_type.linked_packages.filter(is_active=True, is_purchasable=True)
                    ],
                    'duration': slot.session_type.duration_minutes,
                }
            })

        # Also include ScheduleBlock records (coach portal schedule)
        sb_queryset = ScheduleBlock.objects.filter(
            status='available'
        ).select_related('coach').prefetch_related('catalog_session_types')
        if start_date:
            sb_queryset = sb_queryset.filter(date__gte=start_date)
        if end_date:
            sb_queryset = sb_queryset.filter(date__lte=end_date)
        if coach_id:
            sb_queryset = sb_queryset.filter(coach_id=coach_id)

        team_coach = is_team_coach(request.user)

        for block in sb_queryset:
            cal = SCHEDULE_BLOCK_CALENDARS.get(block.session_type, SCHEDULE_BLOCK_CALENDARS['group'])
            catalog_types = list(block.catalog_session_types.all())
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
                        for p in (catalog_types[0].linked_packages.filter(is_active=True, is_purchasable=True) if catalog_types else [])
                    ],
                    'duration': dur,
                    'location': block.location_override or (catalog_types[0].location if catalog_types else ''),
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
            slot_type = data.get('slot_type', 'availability_slot')
            player_id = data.get('player_id')
            package_id = data.get('package_id')
            promo_code_str = data.get('promo_code', '').strip().upper()

            # Check package if provided
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

            if slot_type == 'schedule_block':
                # Book against a ScheduleBlock (coach portal schedule)
                block = ScheduleBlock.objects.get(pk=slot_id)
                if not block.is_available:
                    return Response({'error': 'This slot is no longer available'},
                                  status=status.HTTP_400_BAD_REQUEST)

                # Prevent duplicate: same player already has a booking at this date/time
                if player_id and Booking.objects.filter(
                    player_id=player_id,
                    scheduled_date=block.date,
                    scheduled_time=block.start_time,
                    status__in=['pending', 'confirmed'],
                ).exists():
                    return Response(
                        {'error': 'This player already has a booking for this session.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Use first catalog session type if set, otherwise find by format
                catalog_types = list(block.catalog_session_types.all())
                session_type = catalog_types[0] if catalog_types else SessionType.objects.filter(
                    session_format='private' if block.session_type == 'private' else 'clinic',
                    is_active=True
                ).first()

                booking = Booking.objects.create(
                    client=client,
                    player_id=player_id,
                    coach=block.coach,
                    availability_slot=None,
                    session_type=session_type,
                    scheduled_date=block.date,
                    scheduled_time=block.start_time,
                    duration_minutes=block.duration_minutes,
                    status='pending',
                    client_notes=data.get('notes', ''),
                )
                # Mark the block as booked
                block.current_participants += 1
                if block.current_participants >= block.max_participants:
                    block.status = 'booked'
                block.save()

                session_name = session_type.name if session_type else SCHEDULE_BLOCK_CALENDARS.get(block.session_type, {}).get('name', 'Training Session')

            else:
                # Book against an AvailabilitySlot
                slot = AvailabilitySlot.objects.get(pk=slot_id)
                if not slot.is_available:
                    return Response({'error': 'This slot is no longer available'},
                                  status=status.HTTP_400_BAD_REQUEST)

                if player_id and Booking.objects.filter(
                    player_id=player_id,
                    scheduled_date=slot.date,
                    scheduled_time=slot.start_time,
                    status__in=['pending', 'confirmed'],
                ).exists():
                    return Response(
                        {'error': 'This player already has a booking for this session.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

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
                session_name = slot.session_type.name

            # Determine amount due (from slot price or session type)
            try:
                if slot_type == 'schedule_block':
                    st_drop_in = catalog_types[0].get_drop_in_price() if catalog_types else Decimal('0')
                    base_amount = block.price_override if block.price_override else st_drop_in
                    sf = catalog_types[0].session_format if catalog_types else block.session_type
                else:
                    base_amount = slot.session_type.get_drop_in_price()
                    sf = slot.session_type.session_format
                # Apply APC Select discount if applicable
                if get_client_select_membership(request.user):
                    discounted = apply_select_discount(base_amount, sf)
                    amount_due = discounted if discounted is not None else base_amount
                else:
                    amount_due = base_amount
            except Exception:
                amount_due = Decimal('0')

            # If session type does not allow package use, force drop-in regardless
            _st = session_type if 'session_type' in dir() and session_type else None
            if package and _st and not _st.allow_package:
                package = None  # ignore package — charge drop-in rate

            # requires_package enforcement:
            # If requires_package=True and no package provided:
            #   - drop_in_price set  → allow as drop-in at that price
            #   - drop_in_price null → block entirely (package required)
            if not package and _st and _st.requires_package:
                has_drop_in = _st.drop_in_price is not None and _st.drop_in_price > 0
                if not has_drop_in:
                    booking.delete()  # clean up the just-created booking
                    linked = [p.name for p in _st.linked_packages.filter(is_active=True, is_purchasable=True)[:4]]
                    return Response({
                        'error': f'A package is required to book "{_st.name}". Drop-in is not available for this session.',
                        'required_packages': linked,
                    }, status=status.HTTP_400_BAD_REQUEST)
                # drop_in_price is set — allow, amount_due already calculated from drop_in_price

            # If session has specific linked packages, verify client's package is one of them
            if package and _st and _st.linked_packages.exists():
                linked_ids = set(_st.linked_packages.values_list('pk', flat=True))
                if package.package.pk not in linked_ids:
                    if _st.requires_package:
                        has_drop_in = _st.drop_in_price is not None and _st.drop_in_price > 0
                        if has_drop_in:
                            # Incompatible package but drop-in allowed — charge drop-in
                            package = None  # amount_due already set to get_drop_in_price() above
                        else:
                            # No drop-in — block entirely
                            booking.delete()
                            return Response({
                                'error': f'Your current package does not include "{_st.name}". '
                                         f'Please purchase one of the required packages to book this session.',
                                'required_packages': [p.name for p in _st.linked_packages.filter(is_active=True, is_purchasable=True)[:4]],
                            }, status=status.HTTP_400_BAD_REQUEST)
                    else:
                        # Optional package — fall back to drop-in pricing
                        package = None

            # Apply promo code discount to drop-in amount (not stacked with package)
            discount_code_obj = None
            promo_discount = Decimal('0.00')
            if promo_code_str and not package and amount_due and amount_due > 0:
                try:
                    from clients.models import DiscountCode
                    dc = DiscountCode.objects.get(code=promo_code_str, is_active=True)
                    ok, _ = dc.is_valid_now()
                    if ok and dc.scope in ('all', 'sessions'):
                        if _st and dc.specific_session_types.exists() and not dc.specific_session_types.filter(pk=_st.pk).exists():
                            pass  # code not valid for this session type
                        elif dc.min_purchase_amount and amount_due < dc.min_purchase_amount:
                            pass  # minimum not met
                        else:
                            client_uses = dc.uses.filter(client=client, status='applied').count()
                            if client_uses < dc.max_uses_per_client:
                                promo_discount = dc.compute_discount(amount_due)
                                amount_due = max(amount_due - promo_discount, Decimal('0.00'))
                                discount_code_obj = dc
                except Exception:
                    pass  # never block a booking due to promo code failure

            if package:
                # Package booking — session deducted, no separate payment
                booking.use_package(package)
                booking.confirm()
                payment_required = False
                # payment_status is set to 'package' by use_package()
            elif amount_due and amount_due > 0:
                # Pay-now booking with a cost — hold as pending until payment received
                booking.payment_status = 'pending'
                booking.amount_paid = amount_due
                booking.save()
                payment_required = True
                # Track pending promo use — finalised by webhook on payment success
                if discount_code_obj and promo_discount > 0:
                    from clients.models import DiscountCodeUse
                    DiscountCodeUse.objects.create(
                        code=discount_code_obj,
                        client=client,
                        discount_amount=promo_discount,
                        original_amount=amount_due + promo_discount,
                        final_amount=amount_due,
                        status='pending',
                        applied_to_booking=booking,
                    )
                # Notify coach and owner about pending payment booking
                _notify_pending_payment(booking, amount_due)
            else:
                # Free session (price = $0) — confirm directly, mark payment n/a
                booking.payment_status = 'paid'  # free = no payment needed
                booking.save(update_fields=['payment_status'])
                booking.confirm()
                payment_required = False

            return Response({
                'id': booking.id,
                'payment_required': payment_required,
                'amount_due': str(amount_due),
                'discount_applied': str(promo_discount),
                'booking_status': booking.status,
                'message': 'Booking created successfully',
                'booking': {
                    'date': str(booking.scheduled_date),
                    'time': str(booking.scheduled_time),
                    'session_type': session_name,
                    'coach': str(booking.coach),
                }
            }, status=status.HTTP_201_CREATED)

        except ScheduleBlock.DoesNotExist:
            return Response({'error': 'Schedule block not found'}, status=status.HTTP_404_NOT_FOUND)
        except AvailabilitySlot.DoesNotExist:
            return Response({'error': 'Availability slot not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception('Booking creation failed: slot_id=%s slot_type=%s player_id=%s',
                             data.get('slot_id'), data.get('slot_type'), data.get('player_id'))
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
            'package_id': pkg.package_id,
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
