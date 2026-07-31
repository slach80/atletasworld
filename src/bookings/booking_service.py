"""
Booking creation service — pure business logic, no HTTP concerns.

Called by BookingViewSet.create in api.py. Can also be invoked directly
in tests or background tasks without the HTTP layer.
"""
import logging
from decimal import Decimal
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from bookings.models import AvailabilitySlot, Booking, SessionType
from bookings.utils import (
    apply_select_discount,
    get_client_select_membership,
    notify_pending_payment as _notify_pending_payment,
    SELECT_PICKUP_PRICE,
    SELECT_DISCOUNT_FORMATS,
    SELECT_PICKUP_FORMATS,
)
from coaches.models import ScheduleBlock
from clients.models import Client, ClientPackage, Package, Player

logger = logging.getLogger(__name__)

SCHEDULE_BLOCK_CALENDARS = {
    'private': {'id': 'sb_private', 'name': 'Private Training', 'color': '#1a1a1a'},
    'group':   {'id': 'sb_group',   'name': 'Group Training',   'color': '#D7FF00'},
}


class BookingError(Exception):
    """Raised for any booking validation failure. Carries status_code and extra payload."""

    def __init__(self, message, status_code=400, extra=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.extra = extra or {}


def create_booking(user, slot_id, slot_type, player_id, package_id, promo_code_str, notes):
    """
    Create a booking. Returns a result dict on success, raises BookingError on failure.

    Parameters match what BookingViewSet.create reads from request.data, with
    promo_code_str already stripped and uppercased by the caller.

    The entire function runs inside transaction.atomic() so that the slot/block
    row lock (select_for_update) and the booking row are committed together or
    rolled back atomically on any error.
    """
    with transaction.atomic():
        return _create_booking_inner(user, slot_id, slot_type, player_id, package_id, promo_code_str, notes)


def _create_booking_inner(user, slot_id, slot_type, player_id, package_id, promo_code_str, notes):
    if not hasattr(user, 'client'):
        raise BookingError('Only clients can create bookings', 403)

    client = user.client

    # Waiver gate — exempt staff/owners/coaches, block everyone else without a signed waiver
    is_exempt = (
        user.is_staff or user.is_superuser
        or user.groups.filter(name__in=['Owner', 'Coach']).exists()
        or hasattr(user, 'coach')
    )
    if not is_exempt:
        from clients.models import get_current_waiver
        if not get_current_waiver(client):
            raise BookingError(
                'Annual waiver required. Please sign it in your Profile before booking.',
                403,
            )

    # Verify player belongs to authenticated client
    if player_id:
        if not Player.objects.filter(pk=player_id, client=client, is_active=True).exists():
            raise BookingError('Player not found', 404)

    # Check or auto-select package (player-aware)
    package = None
    if package_id:
        try:
            package = ClientPackage.objects.get(pk=package_id, client=client)
            if package.sessions_remaining <= 0:
                raise BookingError(
                    'No sessions remaining in package',
                    400,
                    {'upgrade_available': True, 'message': 'Would you like to upgrade your package?'},
                )
            if not package.is_valid:
                raise BookingError('Package is expired or inactive', 400)
        except ClientPackage.DoesNotExist:
            raise BookingError('Package not found', 404)
    else:
        # Auto-select package if not provided: prefer player-specific, fallback to unassigned
        if player_id:
            package = client.packages.filter(
                status='active',
                expiry_date__gte=timezone.localdate(),
                player_id=player_id
            ).exclude(
                package__sessions_included__gt=0,
                sessions_remaining=0
            ).order_by('-sessions_remaining').first()

            # Fallback to unassigned package with sessions
            if not package:
                package = client.packages.filter(
                    status='active',
                    expiry_date__gte=timezone.localdate(),
                    player__isnull=True
                ).exclude(
                    package__sessions_included__gt=0,
                    sessions_remaining=0
                ).order_by('-sessions_remaining').first()

    session_type = None  # initialised here; set inside the schedule_block branch only

    if slot_type == 'schedule_block':
        # Book against a ScheduleBlock — lock the row to prevent concurrent oversell.
        try:
            block = ScheduleBlock.objects.select_for_update().get(pk=slot_id, status='available')
        except ScheduleBlock.DoesNotExist:
            raise BookingError('This slot is no longer available', 400)
        if not block.is_available:
            raise BookingError('This slot is no longer available', 400)

        # Prevent duplicate: same player already has a booking at this date/time
        if player_id and Booking.objects.filter(
            player_id=player_id,
            scheduled_date=block.date,
            scheduled_time=block.start_time,
            status__in=['pending', 'confirmed'],
        ).exists():
            raise BookingError('This player already has a booking for this session.', 400)

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
            client_notes=notes,
        )
        session_name = session_type.name if session_type else SCHEDULE_BLOCK_CALENDARS.get(block.session_type, {}).get('name', 'Training Session')

        # --- APC Select routing ---
        sf_check = catalog_types[0].session_format if catalog_types else None
        if sf_check in ('select_practice', 'select_game') and not is_exempt:
            if not get_client_select_membership(user):
                booking.delete()
                raise BookingError('APC Select membership required to book this session.', 400)
            if sf_check == 'select_game':
                block.current_participants = F('current_participants') + 1
                block.save(update_fields=['current_participants'])
                block.refresh_from_db(fields=['current_participants', 'max_participants'])
                if block.current_participants >= block.max_participants:
                    ScheduleBlock.objects.filter(pk=block.pk).update(status='booked')
                booking.payment_status = 'paid'
                booking.amount_paid = Decimal('0.00')
                booking.save(update_fields=['payment_status', 'amount_paid'])
                booking.confirm()
                try:
                    from clients.notification_utils import queue_grouped_notification
                    queue_grouped_notification(
                        client=booking.client,
                        event_type='booking_confirmed',
                        context={'booking_id': booking.id, 'payment_method': 'select'},
                        group_key=f'booking_{booking.id}',
                        window_seconds=45,
                    )
                except Exception:
                    pass
                return {
                    'id': booking.id, 'payment_required': False,
                    'amount_due': '0.00', 'discount_applied': '0.00',
                    'sibling_discount': '0.00', 'booking_status': booking.status,
                    'message': 'Booking created successfully',
                    'booking': {
                        'date': str(booking.scheduled_date), 'time': str(booking.scheduled_time),
                        'session_type': session_name, 'coach': str(booking.coach),
                    },
                }
            if sf_check == 'select_practice':
                month_start = timezone.localdate().replace(day=1)
                # Count confirmed Select practice bookings this month for this player
                # Match by session_type FK (the APC Select Practice session type)
                select_practice_type_ids = list(
                    SessionType.objects.filter(
                        session_format='select_practice', is_active=True
                    ).values_list('id', flat=True)
                )
                # Upper bound: first day of next month
                if month_start.month == 12:
                    month_end = month_start.replace(year=month_start.year + 1, month=1)
                else:
                    month_end = month_start.replace(month=month_start.month + 1)
                month_count = Booking.objects.filter(
                    player_id=player_id,
                    session_type_id__in=select_practice_type_ids,
                    status='confirmed',
                    scheduled_date__gte=month_start,
                    scheduled_date__lt=month_end,
                ).exclude(pk=booking.pk).count()
                if month_count < 2:
                    block.current_participants = F('current_participants') + 1
                    block.save(update_fields=['current_participants'])
                    block.refresh_from_db(fields=['current_participants', 'max_participants'])
                    if block.current_participants >= block.max_participants:
                        ScheduleBlock.objects.filter(pk=block.pk).update(status='booked')
                    booking.payment_status = 'paid'
                    booking.amount_paid = Decimal('0.00')
                    booking.save(update_fields=['payment_status', 'amount_paid'])
                    booking.confirm()
                    try:
                        from clients.notification_utils import queue_grouped_notification
                        queue_grouped_notification(
                            client=booking.client,
                            event_type='booking_confirmed',
                            context={'booking_id': booking.id, 'payment_method': 'select'},
                            group_key=f'booking_{booking.id}',
                            window_seconds=45,
                        )
                    except Exception:
                        pass
                    return {
                        'id': booking.id, 'payment_required': False,
                        'amount_due': '0.00', 'discount_applied': '0.00',
                        'sibling_discount': '0.00', 'booking_status': booking.status,
                        'message': 'Booking created successfully',
                        'booking': {
                            'date': str(booking.scheduled_date), 'time': str(booking.scheduled_time),
                            'session_type': session_name, 'coach': str(booking.coach),
                        },
                    }
                # 3rd+ practice — fall through to normal package/drop-in flow

    else:
        # Book against an AvailabilitySlot — only fetch publicly available slots
        try:
            slot = AvailabilitySlot.objects.get(
                pk=slot_id, status__in=['available', 'partially_booked']
            )
        except AvailabilitySlot.DoesNotExist:
            raise BookingError('This slot is no longer available', 400)
        if not slot.is_available:
            raise BookingError('This slot is no longer available', 400)

        if player_id and Booking.objects.filter(
            player_id=player_id,
            scheduled_date=slot.date,
            scheduled_time=slot.start_time,
            status__in=['pending', 'confirmed'],
        ).exists():
            raise BookingError('This player already has a booking for this session.', 400)

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
            client_notes=notes,
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
        if get_client_select_membership(user):
            discounted = apply_select_discount(base_amount, sf)
            amount_due = discounted if discounted is not None else base_amount
        else:
            amount_due = base_amount
    except Exception:
        amount_due = Decimal('0')

    # If session type does not allow package use, force drop-in regardless
    _st = session_type if session_type is not None else None
    if package and _st and not _st.allow_package:
        package = None  # ignore package — charge drop-in rate

    # requires_package enforcement:
    # If requires_package=True and no package provided:
    #   - drop_in_price set  → allow as drop-in at that price
    #   - drop_in_price null → block entirely (package required)
    # Owner/staff/coaches are exempt from package requirements.
    if not is_exempt and not package and _st and _st.requires_package:
        has_drop_in = _st.drop_in_price is not None and _st.drop_in_price > 0
        if not has_drop_in:
            booking.delete()  # clean up the just-created booking
            linked = [p.name for p in _st.linked_packages.filter(is_active=True, is_purchasable=True)[:4]]
            raise BookingError(
                f'A package is required to book "{_st.name}". Drop-in is not available for this session.',
                400,
                {'required_packages': linked},
            )
        # drop_in_price is set — allow, amount_due already calculated from drop_in_price

    # If session has specific linked packages, verify client's package is one of them
    # Owner/staff/coaches can book any session type regardless of linked packages.
    if not is_exempt and package and _st and _st.linked_packages.exists():
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
                    raise BookingError(
                        f'Your current package does not include "{_st.name}". '
                        f'Please purchase one of the required packages to book this session.',
                        400,
                        {'required_packages': [p.name for p in _st.linked_packages.filter(is_active=True, is_purchasable=True)[:4]]},
                    )
            else:
                # Optional package — fall back to drop-in pricing
                package = None

    # Sibling discount: another player under same client already booked this slot?
    # Only applies to group-format sessions, not private/semi-private.
    GROUP_FORMATS = {'group', 'clinic', 'camp', 'seasonal', 'pickup', 'team'}
    sibling_session_discount = Decimal('0.00')
    sibling_session_found = False
    if not package and amount_due and amount_due > 0 and player_id and sf in GROUP_FORMATS:
        try:
            if slot_type == 'schedule_block':
                sibling_booked = Booking.objects.filter(
                    client=client,
                    scheduled_date=block.date,
                    scheduled_time=block.start_time,
                    status__in=['pending', 'confirmed'],
                ).exclude(player_id=player_id).exists()
            else:
                sibling_booked = Booking.objects.filter(
                    client=client,
                    availability_slot=slot,
                    status__in=['pending', 'confirmed'],
                ).exclude(player_id=player_id).exists()
            if sibling_booked:
                sibling_session_discount = (amount_due * Decimal('50') / Decimal('100')).quantize(Decimal('0.01'))
                amount_due = max(amount_due - sibling_session_discount, Decimal('0.00'))
                sibling_session_found = True
        except Exception:
            pass  # never block a booking due to sibling detection failure

    # Apply promo code discount to drop-in amount (not stacked with sibling discount)
    discount_code_obj = None
    promo_discount = Decimal('0.00')
    if promo_code_str and not package and amount_due and amount_due > 0 and not sibling_session_found:
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

    # All validation passed — now increment the slot/block participant counter atomically.
    if slot_type == 'schedule_block':
        block.current_participants = F('current_participants') + 1
        block.save(update_fields=['current_participants'])
        block.refresh_from_db(fields=['current_participants', 'max_participants'])
        if block.current_participants >= block.max_participants:
            ScheduleBlock.objects.filter(pk=block.pk).update(status='booked')
    else:
        slot.current_bookings = F('current_bookings') + 1
        slot.save(update_fields=['current_bookings'])
        slot.refresh_from_db(fields=['current_bookings', 'max_bookings'])
        if slot.current_bookings >= slot.max_bookings:
            AvailabilitySlot.objects.filter(pk=slot.pk).update(status='fully_booked')
        elif slot.current_bookings > 0:
            AvailabilitySlot.objects.filter(pk=slot.pk, status='available').update(status='partially_booked')

    if package:
        # CRITICAL VALIDATION: Prevent special event packages from booking other special events
        # Special event packages (camps, clinics) should only be used for that specific event
        # If the session is a camp/clinic/special event, require payment instead of allowing package use
        is_special_event_session = _st and _st.session_format in ('camp', 'clinic')
        is_special_event_package = package.package.is_special or package.package.package_type == 'special'

        if is_special_event_package and is_special_event_session:
            # Block: special event package cannot pay for another special event
            # Force drop-in payment for this camp/clinic
            booking.delete()
            raise BookingError(
                f'Special event packages cannot be used to book other camps or clinics. '
                f'Please purchase a separate package or pay the drop-in price of ${amount_due}.',
                400,
                {'amount_due': str(amount_due), 'payment_required': True},
            )

        # Package booking — session deducted, no separate payment
        booking.use_package(package)
        booking.confirm()
        payment_required = False
        # payment_status is set to 'package' by use_package()
        # Queue confirmation email (45s window)
        try:
            from clients.notification_utils import queue_grouped_notification
            queue_grouped_notification(
                client=booking.client,
                event_type='booking_confirmed',
                context={
                    'booking_id': booking.id,
                    'payment_method': 'package',
                    'package_name': package.package.name,
                    'sessions_remaining': package.sessions_remaining,
                },
                group_key=f'booking_{booking.id}',
                window_seconds=45,
            )
        except Exception:
            pass  # never block booking on notification failure
    elif amount_due and amount_due > 0:
        # Pay-now booking with a cost — hold as pending until payment received
        booking.payment_status = 'pending'
        booking.amount_paid = amount_due
        booking.save()
        payment_required = True
        # Queue reservation email (2-min window — catches most Stripe webhooks)
        try:
            from clients.notification_utils import queue_grouped_notification
            from django.utils import timezone as _tz
            deadline = (_tz.now() + timedelta(hours=24)).strftime('%A, %B %-d at %-I:%M %p')
            queue_grouped_notification(
                client=booking.client,
                event_type='booking_reserved',
                context={
                    'booking_id': booking.id,
                    'amount_due': float(amount_due),
                    'payment_deadline': deadline,
                },
                group_key=f'booking_{booking.id}',
                window_seconds=120,
            )
        except Exception:
            pass
        # Track sibling discount use — finalised by webhook on payment success
        if sibling_session_found and sibling_session_discount > 0:
            from clients.models import DiscountCode, DiscountCodeUse
            sibling_dc, _ = DiscountCode.objects.get_or_create(
                code='SIBLING-AUTO',
                defaults={
                    'description': 'Automatic sibling discount (50% off group sessions)',
                    'discount_type': 'percent',
                    'value': Decimal('50.00'),
                    'scope': 'all',
                    'max_uses': None,
                    'max_uses_per_client': 99,
                    'is_active': True,
                }
            )
            DiscountCodeUse.objects.create(
                code=sibling_dc,
                client=client,
                discount_amount=sibling_session_discount,
                original_amount=amount_due + sibling_session_discount,
                final_amount=amount_due,
                status='pending',
                applied_to_booking=booking,
            )
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
        try:
            from clients.notification_utils import queue_grouped_notification
            queue_grouped_notification(
                client=booking.client,
                event_type='booking_confirmed',
                context={'booking_id': booking.id, 'payment_method': 'paid'},
                group_key=f'booking_{booking.id}',
                window_seconds=45,
            )
        except Exception:
            pass
        payment_required = False

    return {
        'id': booking.id,
        'payment_required': payment_required,
        'amount_due': str(amount_due),
        'discount_applied': str(promo_discount),
        'sibling_discount': str(sibling_session_discount),
        'booking_status': booking.status,
        'message': 'Booking created successfully',
        'booking': {
            'date': str(booking.scheduled_date),
            'time': str(booking.scheduled_time),
            'session_type': session_name,
            'coach': str(booking.coach),
        },
    }
