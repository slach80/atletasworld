import json
import logging
from datetime import datetime, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.db.models import Sum, Q
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings

from clients.models import Client, Player, Package, ClientPackage, SessionReservation, BookingPreference, FieldRentalSlot, ClientWaiver, get_current_waiver
from bookings.models import Booking, Program, AvailabilitySlot
from coaches.models import Coach, ScheduleBlock

logger = logging.getLogger(__name__)


@login_required
def bookings_list(request):
    """List all bookings for the client."""
    client, created = Client.objects.get_or_create(user=request.user)

    upcoming_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__gte=timezone.localdate(),
        status__in=['pending', 'confirmed']
    ).exclude(
        payment_status='pending', client_package__isnull=True, session_type__price__gt=0
    ).select_related('player', 'session_type', 'coach').order_by('scheduled_date', 'scheduled_time')

    past_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__lt=timezone.localdate()
    ).select_related('player', 'session_type', 'coach').order_by('-scheduled_date', '-scheduled_time')[:200]

    from django.conf import settings as django_settings
    from clients.services import _location_map_url

    all_bookings = list(upcoming_bookings) + list(past_bookings)

    # Batch-resolve block location overrides — one query instead of one per booking.
    dates = {b.scheduled_date for b in all_bookings}
    block_location_map = {
        (bl.coach_id, bl.date, bl.start_time): bl.location_override
        for bl in ScheduleBlock.objects.filter(date__in=dates).only(
            'coach_id', 'date', 'start_time', 'location_override'
        )
        if bl.location_override
    }
    for b in all_bookings:
        loc = block_location_map.get((b.coach_id, b.scheduled_date, b.scheduled_time))
        if not loc:
            loc = b.session_type.location if b.session_type else ''
        b.effective_location = loc
        b.effective_location_map_url = _location_map_url(loc)

    context = {
        'client': client,
        'upcoming_bookings': upcoming_bookings,
        'past_bookings': past_bookings,
        'stripe_public_key': django_settings.STRIPE_PUBLIC_KEY,
    }
    return render(request, 'clients/bookings.html', context)


@login_required
@require_POST
def booking_cancel(request, booking_id):
    """Cancel a booking."""
    client, created = Client.objects.get_or_create(user=request.user)
    booking = get_object_or_404(Booking, id=booking_id, client=client)

    # Unpaid pending bookings are always cancellable (no 24h restriction)
    is_unpaid_pending = booking.status == 'pending' and booking.payment_status == 'pending'
    if is_unpaid_pending or booking.can_cancel or booking.status in ['pending', 'confirmed']:
        try:
            booking.cancel(reason='client_request', cancelled_by=request.user)
            messages.success(request, 'Booking has been cancelled.')
        except Exception:
            # Fallback: manual cancel + ScheduleBlock cleanup
            booking.status = 'cancelled'
            booking.save()
            from coaches.models import ScheduleBlock
            try:
                block = ScheduleBlock.objects.get(
                    coach=booking.coach,
                    date=booking.scheduled_date,
                    start_time=booking.scheduled_time,
                )
                if block.current_participants > 0:
                    block.current_participants -= 1
                    if block.status == 'booked':
                        block.status = 'available'
                    block.save()
            except ScheduleBlock.DoesNotExist:
                pass
            messages.success(request, 'Booking has been cancelled.')
        try:
            from clients.services import NotificationService
            NotificationService.send_booking_cancellation(booking)
        except Exception:
            pass
    else:
        messages.error(request, 'This booking cannot be cancelled.')

    return redirect('clients:bookings')


@login_required
def booking_reschedule(request, booking_id):
    """Show available slots and process reschedule for an existing booking."""
    client, _ = Client.objects.get_or_create(user=request.user)
    booking = get_object_or_404(Booking, id=booking_id, client=client)

    if booking.status in ['cancelled', 'completed', 'no_show']:
        messages.error(request, 'This booking cannot be rescheduled.')
        return redirect('clients:bookings')

    if request.method == 'POST':
        block_id = request.POST.get('slot_id')
        new_block = get_object_or_404(ScheduleBlock, id=block_id)
        if not new_block.is_available:
            messages.error(request, 'That slot is no longer available. Please choose another.')
            return redirect('clients:booking_reschedule', booking_id=booking_id)
        # Verify the target block supports the same session type as the original booking.
        if booking.session_type and not new_block.catalog_session_types.filter(pk=booking.session_type_id).exists():
            messages.error(request, 'That slot does not support the session type of your original booking.')
            return redirect('clients:booking_reschedule', booking_id=booking_id)
        try:
            new_booking = Booking.objects.create(
                client=booking.client,
                player=booking.player,
                coach=new_block.coach,
                session_type=booking.session_type,
                client_package=booking.client_package,
                scheduled_date=new_block.date,
                scheduled_time=new_block.start_time,
                duration_minutes=new_block.duration_minutes,
                status='confirmed',
                payment_status=booking.payment_status,
                amount_paid=booking.amount_paid,
                rescheduled_from=booking,
                client_notes=booking.client_notes,
            )
            new_block.current_participants += 1
            if new_block.current_participants >= new_block.max_participants:
                new_block.status = 'booked'
            new_block.save()
            booking.status = 'cancelled'
            booking.cancellation_reason = 'rescheduled'
            booking.cancellation_notes = f'Rescheduled to {new_block.date}'
            booking.cancelled_at = timezone.now()
            booking.cancelled_by = request.user
            booking.save()
            # Send confirmation email for the new booking
            try:
                from clients.notification_utils import queue_grouped_notification
                queue_grouped_notification(
                    client=client,
                    event_type='booking_confirmed',
                    context={'booking_id': new_booking.id, 'payment_method': new_booking.payment_status, 'rescheduled': True},
                    group_key=f'booking_{new_booking.id}',
                    window_seconds=30,
                )
            except Exception:
                pass
            # Send rescheduled notice for the old (cancelled) booking
            try:
                from clients.services import NotificationService
                NotificationService.send_booking_cancellation(booking, rescheduled=True)
            except Exception:
                pass
            messages.success(request, f'Booking rescheduled to {new_block.date.strftime("%B %-d")} at {new_block.start_time.strftime("%-I:%M %p")}.')
        except Exception as e:
            messages.error(request, f'Could not reschedule: {e}')
        return redirect('clients:bookings')

    # GET: find available ScheduleBlocks for same coach + session type, next 60 days
    today = timezone.localdate()
    available_slots = ScheduleBlock.objects.filter(
        coach=booking.coach,
        date__gt=today,
        date__lte=today + timedelta(days=60),
        status='available',
    )
    if booking.session_type:
        available_slots = available_slots.filter(catalog_session_types=booking.session_type)
    # Exclude the block the original booking was on
    available_slots = available_slots.exclude(
        date=booking.scheduled_date,
        start_time=booking.scheduled_time,
    ).order_by('date', 'start_time')
    available_slots = [b for b in available_slots if b.is_available]

    return render(request, 'clients/booking_reschedule.html', {
        'booking': booking,
        'available_slots': available_slots,
    })


@login_required
def booking_page(request):
    """Main booking page with package info and session selection."""
    client, created = Client.objects.get_or_create(user=request.user)

    # Waiver gate — must be signed before booking (exempt: staff, owners, coaches)
    is_exempt = (
        request.user.is_staff
        or request.user.is_superuser
        or request.user.groups.filter(name__in=['Owner', 'Coach']).exists()
        or hasattr(request.user, 'coach')
    )
    current_waiver = get_current_waiver(client)
    # Profile completeness gate — must have name, phone, emergency contact + waiver
    if not is_exempt:
        missing = []
        if not request.user.first_name or not request.user.last_name:
            missing.append('your name')
        if not client.phone:
            missing.append('phone number')
        if not client.emergency_contact:
            missing.append('emergency contact')
        if not current_waiver:
            missing.append('annual waiver')
        if missing:
            messages.warning(request, f'Please complete your profile before booking — missing: {", ".join(missing)}.')
            return redirect('clients:profile')

        # Require at least one player before booking
        # Fetch players once — reuse for guard check and context
        players = list(client.players.filter(is_active=True))
        if not players:
            messages.info(request, 'Please add a player before booking a session.')
            return redirect(f"{reverse('clients:player_add')}?next={reverse('clients:book')}")
    else:
        players = list(client.players.filter(is_active=True))

    booking_prefs, _ = BookingPreference.objects.get_or_create(client=client)

    # Throttle cleanup to once every 5 minutes to avoid a full table scan on every load
    _cleanup_key = 'session_reservation_cleanup'
    if not cache.get(_cleanup_key):
        SessionReservation.cleanup_expired()
        cache.set(_cleanup_key, True, 300)

    # Get client's active packages (may have multiple for different players)
    active_packages_qs = client.packages.filter(
        status='active',
        expiry_date__gte=timezone.localdate()
    ).select_related('package', 'player')

    # For backward compatibility, keep active_package as first one
    active_package = active_packages_qs.first()

    # Get coaches
    coaches = Coach.objects.filter(is_active=True)

    # Get programs
    programs = Program.objects.filter(is_active=True)

    # Get available schedule blocks (next 30 days)
    today = timezone.localdate()
    available_blocks = ScheduleBlock.objects.filter(
        date__gte=today,
        date__lte=today + timedelta(days=30),
        status='available'
    ).select_related('coach').order_by('date', 'start_time')

    # Calculate upgrade options if client has a package
    upgrade_options = []
    if active_package:
        upgrade_options = active_package.get_upgrade_options()

    # Available packages for purchase (if no active package) - exclude special and team
    regular_packages = Package.objects.filter(
        is_active=True, is_purchasable=True,
        is_special=False
    ).exclude(package_type='team').order_by('price')

    # Special event packages (always shown)
    special_packages = Package.objects.filter(
        is_active=True, is_purchasable=True,
        is_special=True,
        event_end_date__gte=today
    ).order_by('event_start_date')

    # Team packages (only for team coaches/managers)
    team_packages = []
    if client.client_type == 'coach':
        team_packages = Package.objects.filter(
            is_active=True,
            package_type='team'
        ).order_by('price')

    # Check if client has purchased any special packages
    client_special_packages = client.packages.filter(
        package__is_special=True,
        status__in=['active', 'exhausted']
    ).select_related('package')

    # Get client's current reservations
    current_reservations = SessionReservation.objects.filter(
        client=client,
        is_confirmed=False,
        expires_at__gt=timezone.now()
    )

    # Get existing bookings for conflict detection
    existing_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__gte=today,
        status__in=['pending', 'confirmed']
    ).select_related('player')

    # APC Select membership check — for discount display
    has_select_membership = client.packages.filter(
        package__package_type='select',
        status='active',
        expiry_date__gte=today,
    ).exists()
    select_credit_balance = client.credits.filter(
        status='available'
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=today)
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Get favorite coach IDs for template
    favorite_coach_ids = list(booking_prefs.favorite_coaches.values_list('id', flat=True))

    # Pre-select coach filter from ?coach_id=<int> query param
    preselect_coach_id_raw = request.GET.get('coach_id', '')
    preselect_coach_id = int(preselect_coach_id_raw) if preselect_coach_id_raw.isdigit() else None

    # Get blocked dates from special packages (dates when special events are happening)
    # Optimized: Generate date ranges more efficiently
    blocked_dates = []
    for sp in special_packages:
        if sp.event_start_date and sp.event_end_date:
            # Calculate days difference and generate all dates at once
            days_diff = (sp.event_end_date - sp.event_start_date).days + 1
            blocked_dates.extend([
                (sp.event_start_date + timedelta(days=i)).isoformat()
                for i in range(days_diff)
            ])

    # Build player → package mapping for frontend
    import json
    player_packages = {}
    for pkg in active_packages_qs:
        if pkg.player_id:
            player_packages[str(pkg.player_id)] = {
                'id': pkg.id,
                'name': pkg.package.name,
                'sessions_remaining': pkg.sessions_remaining,
                'sessions_included': pkg.package.sessions_included,
            }
    player_packages_json = json.dumps(player_packages)

    context = {
        'client': client,
        'active_package': active_package,
        'active_packages': list(active_packages_qs),  # All packages
        'player_packages_json': player_packages_json,  # JSON string of player_id → package
        'players': players,
        'coaches': coaches,
        'programs': programs,
        'available_blocks': available_blocks,
        'upgrade_options': upgrade_options,
        'regular_packages': regular_packages,
        'special_packages': special_packages,
        'team_packages': team_packages,
        'client_special_packages': client_special_packages,
        'blocked_dates': blocked_dates,
        'is_team_coach': client.client_type == 'coach',
        'current_reservations': current_reservations,
        'existing_bookings': existing_bookings,
        'has_package': active_package is not None,
        'sessions_remaining': active_package.sessions_remaining if active_package else 0,
        'booking_prefs': booking_prefs,
        'favorite_coach_ids': favorite_coach_ids,
        'preselect_coach_id': preselect_coach_id,
        'has_select_membership': has_select_membership,
        'select_credit_balance': select_credit_balance,
        'stripe_public_key': __import__('django.conf', fromlist=['settings']).settings.STRIPE_PUBLIC_KEY,
        'available_field_rentals': FieldRentalSlot.objects.filter(
            date__gte=today, date__lte=today + timedelta(days=30), status='available'
        ).order_by('date', 'start_time'),
        'booked_field_rentals': list(FieldRentalSlot.objects.filter(
            date__gte=today, date__lte=today + timedelta(days=30),
            status__in=['booked', 'pending_approval']
        ).values('date', 'start_time', 'end_time')),
    }
    # Use new calendar-based booking template
    return render(request, 'clients/book_calendar.html', context)


@login_required
def booking_page_v2(request):
    """New responsive booking page with platform-optimized layouts."""
    client, created = Client.objects.get_or_create(user=request.user)

    # Reuse same context as original booking_page
    # Get active packages
    today = timezone.localdate()
    active_packages_qs = client.packages.filter(
        status='active',
        expiry_date__gte=today
    ).select_related('package', 'player')
    active_package = active_packages_qs.first()

    # Get players
    players = list(client.players.filter(is_active=True))

    # Get coaches
    coaches = Coach.objects.filter(is_active=True)

    # Get existing bookings for duplicate check on frontend
    existing_bookings = Booking.objects.filter(
        client=client,
        status__in=['confirmed', 'pending'],
        scheduled_date__gte=today,
    ).exclude(
        payment_status='pending'
    ).values_list('player_id', 'scheduled_date', 'scheduled_time')
    # Format as set of "player_id|date|time" for quick JS lookup
    booked_set = [
        f"{pid}|{d.isoformat()}|{t.strftime('%H:%M')}"
        for pid, d, t in existing_bookings
    ]

    has_select_membership = client.packages.filter(
        package__package_type='select',
        status='active',
        expiry_date__gte=today,
    ).exists()
    select_credit_balance = client.credits.filter(
        status='available'
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=today)
    ).aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'client': client,
        'active_package': active_package,
        'players': players,
        'coaches': coaches,
        'has_package': active_package is not None,
        'stripe_public_key': settings.STRIPE_PUBLIC_KEY,
        'booked_set_json': json.dumps(booked_set),
        'has_select_membership': has_select_membership,
        'select_credit_balance': select_credit_balance,
    }
    return render(request, 'clients/book_calendar_v2.html', context)


@login_required
@require_POST
def reserve_session(request):
    """Reserve a session slot (temporary hold for 10 minutes)."""
    client, created = Client.objects.get_or_create(user=request.user)

    is_exempt = (
        request.user.is_staff
        or request.user.is_superuser
        or request.user.groups.filter(name__in=['Owner', 'Coach']).exists()
        or hasattr(request.user, 'coach')
    )
    if not is_exempt and not get_current_waiver(client):
        return JsonResponse({'success': False, 'error': 'Annual waiver required. Please sign it in your Profile before booking.'})

    block_id = request.POST.get('block_id')
    player_id = request.POST.get('player_id')

    block = get_object_or_404(ScheduleBlock, id=block_id)
    player = get_object_or_404(Player, id=player_id, client=client)

    # Check if field is exclusively reserved
    if FieldRentalSlot.check_field_blocked(block.date, block.start_time, block.end_time):
        return JsonResponse({'success': False,
            'error': 'The field is exclusively reserved during this time. No other bookings are possible.'})

    # Check if block is still available
    if not block.is_available:
        return JsonResponse({'success': False, 'error': 'Session is no longer available'})

    # Check if this block is free (e.g. tryout / free event) — no package required
    catalog_types = block.catalog_session_types.all()
    block_is_free = (
        block.price_override is not None and block.price_override == 0
    ) or (
        catalog_types.exists() and all(
            (st.drop_in_price is not None and st.drop_in_price == 0) or (st.price == 0 and not st.requires_package)
            for st in catalog_types
        )
    )

    # Check if client has an active package with sessions remaining
    # First, try to find a package assigned to this specific player (with sessions left)
    active_package = client.packages.filter(
        status='active',
        expiry_date__gte=timezone.localdate(),
        player=player
    ).exclude(
        package__sessions_included__gt=0,
        sessions_remaining=0
    ).order_by('-sessions_remaining').first()

    # If no player-specific package, fallback to unassigned packages with sessions
    if not active_package:
        active_package = client.packages.filter(
            status='active',
            expiry_date__gte=timezone.localdate(),
            player__isnull=True
        ).exclude(
            package__sessions_included__gt=0,
            sessions_remaining=0
        ).order_by('-sessions_remaining').first()

    # Check if we have a valid package (owner/staff/coaches bypass this check)
    if not block_is_free and not is_exempt:
        if not active_package:
            return JsonResponse({'success': False, 'error': 'No active package found for this player'})
        if active_package.package.sessions_included > 0 and active_package.sessions_remaining <= 0:
            return JsonResponse({'success': False, 'error': 'No sessions remaining in package'})

    # Check if already reserved by this client
    existing = SessionReservation.objects.filter(
        client=client,
        schedule_block=block,
        player=player,
        is_confirmed=False
    ).exists()

    if existing:
        return JsonResponse({'success': False, 'error': 'Already reserved'})

    # Create reservation (expires in 10 minutes)
    reservation = SessionReservation.objects.create(
        client=client,
        schedule_block=block,
        player=player,
        expires_at=timezone.now() + timedelta(minutes=10)
    )

    # Increment participant count to hold the spot
    block.current_participants += 1
    if block.current_participants >= block.max_participants:
        block.status = 'booked'
    block.save()

    return JsonResponse({
        'success': True,
        'reservation_id': reservation.id,
        'expires_at': reservation.expires_at.isoformat()
    })


@login_required
@require_POST
def cancel_reservation(request):
    """Cancel a pending reservation."""
    client, created = Client.objects.get_or_create(user=request.user)

    reservation_id = request.POST.get('reservation_id')
    reservation = get_object_or_404(SessionReservation, id=reservation_id, client=client, is_confirmed=False)

    # Release the spot
    block = reservation.schedule_block
    if block.current_participants > 0:
        block.current_participants -= 1
        if block.status == 'booked':
            block.status = 'available'
        block.save()

    reservation.delete()

    return JsonResponse({'success': True})


@login_required
@require_POST
def confirm_booking(request):
    """Confirm all pending reservations as actual bookings."""
    client, created = Client.objects.get_or_create(user=request.user)

    # Get all pending reservations
    reservations = SessionReservation.objects.filter(
        client=client,
        is_confirmed=False,
        expires_at__gt=timezone.now()
    )

    if not reservations.exists():
        return JsonResponse({'success': False, 'error': 'No reservations to confirm'})

    # Determine which reservations need a package vs. which are free
    free_reservations = []
    paid_reservations = []
    for res in reservations:
        catalog_types = res.schedule_block.catalog_session_types.all()
        is_free = (
            res.schedule_block.price_override is not None and res.schedule_block.price_override == 0
        ) or (
            catalog_types.exists() and all(
                (st.drop_in_price is not None and st.drop_in_price == 0) or (st.price == 0 and not st.requires_package)
                for st in catalog_types
            )
        )
        if is_free:
            free_reservations.append(res)
        else:
            paid_reservations.append(res)

    def get_package_for_player(player, session_type=None):
        linked_ids = (
            list(session_type.linked_packages.values_list('id', flat=True))
            if session_type is not None else []
        )
        not_exhausted = client.packages.filter(
            status='active',
            expiry_date__gte=timezone.localdate(),
        ).exclude(
            package__sessions_included__gt=0,
            sessions_remaining=0
        )
        if linked_ids:
            # Session type restricts to specific packages — no fallback
            pkg = not_exhausted.filter(player=player, package__id__in=linked_ids).first()
            if not pkg:
                pkg = not_exhausted.filter(player__isnull=True, package__id__in=linked_ids).first()
            return pkg
        # No restriction — any active package works
        pkg = not_exhausted.filter(player=player).first()
        if not pkg:
            pkg = not_exhausted.filter(player__isnull=True).first()
        return pkg

    # Validate all paid reservations have packages before proceeding
    player_package_map = {}
    for res in paid_reservations:
        session_type_for_res = res.schedule_block.catalog_session_types.first()
        pkg = get_package_for_player(res.player, session_type_for_res)
        if not pkg:
            return JsonResponse({
                'success': False,
                'error': f'No active package found for {res.player.first_name}'
            })
        if pkg.package.sessions_included > 0 and pkg.sessions_remaining <= 0:
            return JsonResponse({
                'success': False,
                'error': f'No sessions remaining in package for {res.player.first_name}'
            })
        player_package_map[res.player.id] = pkg

    bookings_created = 0
    for reservation in reservations:
        is_free_res = reservation in free_reservations
        pkg_to_use = player_package_map.get(reservation.player.id) if not is_free_res else None

        booking = Booking.objects.create(
            client=client,
            player=reservation.player,
            coach=reservation.schedule_block.coach,
            scheduled_date=reservation.schedule_block.date,
            scheduled_time=reservation.schedule_block.start_time,
            client_package=pkg_to_use,
            status='confirmed'
        )

        if not is_free_res and pkg_to_use:
            pkg_to_use.use_session()

        reservation.is_confirmed = True
        reservation.save()

        try:
            from clients.notification_utils import queue_grouped_notification
            queue_grouped_notification(
                client=client,
                event_type='booking_confirmed',
                context={'booking_id': booking.id, 'payment_method': 'free' if is_free_res else 'package'},
                group_key=f'booking_{booking.id}',
                window_seconds=30,
            )
        except Exception:
            logger.exception('confirm_booking: notification failed for booking %s', booking.id)

        bookings_created += 1

    # Return total sessions remaining across all packages
    total_sessions = sum(
        pkg.sessions_remaining for pkg in client.packages.filter(
            status='active',
            expiry_date__gte=timezone.localdate()
        ) if pkg.package.sessions_included > 0
    )
    return JsonResponse({
        'success': True,
        'bookings_created': bookings_created,
        'sessions_remaining': total_sessions,
    })


@login_required
@require_POST
def create_booking_direct(request):
    """Create booking directly with immediate package validation (no reservation step)."""
    import json
    import logging
    logger = logging.getLogger(__name__)

    try:
        client, created = Client.objects.get_or_create(user=request.user)

        # Waiver check
        is_exempt = (
            request.user.is_staff
            or request.user.is_superuser
            or request.user.groups.filter(name__in=['Owner', 'Coach']).exists()
            or hasattr(request.user, 'coach')
        )
        if not is_exempt and not get_current_waiver(client):
            return JsonResponse({'success': False, 'error': 'Annual waiver required. Please sign it in your Profile before booking.'})

        # Parse request body
        data = json.loads(request.body)
        bookings_data = data.get('bookings', [])

        if not bookings_data:
            return JsonResponse({'success': False, 'error': 'No bookings provided'})

        def get_package_for_player(player, session_type=None):
            linked_ids = (
                list(session_type.linked_packages.values_list('id', flat=True))
                if session_type is not None else []
            )
            not_exhausted = client.packages.filter(
                status='active',
                expiry_date__gte=timezone.localdate(),
            ).exclude(
                package__sessions_included__gt=0,
                sessions_remaining=0
            )
            if linked_ids:
                # Session type restricts to specific packages — no fallback
                pkg = not_exhausted.filter(player=player, package__id__in=linked_ids).first()
                if not pkg:
                    pkg = not_exhausted.filter(player__isnull=True, package__id__in=linked_ids).first()
                return pkg
            # No restriction — any active package works
            pkg = not_exhausted.filter(player=player).first()
            if not pkg:
                pkg = not_exhausted.filter(player__isnull=True).first()
            return pkg

        # Track sessions consumed during this batch to prevent over-booking
        package_sessions_used = {}  # {client_package_id: count_used_in_this_batch}

        # Validate all bookings first (fail fast)
        validated_bookings = []
        for item in bookings_data:
            block_id = item.get('block_id')
            player_id = item.get('player_id')

            if not block_id or not player_id:
                return JsonResponse({'success': False, 'error': 'Missing block_id or player_id'})

            try:
                block = ScheduleBlock.objects.select_related('coach').prefetch_related('catalog_session_types').get(id=block_id)
                player = Player.objects.get(id=player_id, client=client)
            except (ScheduleBlock.DoesNotExist, Player.DoesNotExist):
                return JsonResponse({'success': False, 'error': 'Invalid block or player'})

            # Check field not blocked
            if FieldRentalSlot.check_field_blocked(block.date, block.start_time, block.end_time):
                return JsonResponse({'success': False, 'error': f'Field is exclusively reserved during {block.date} {block.start_time}'})

            # Check availability
            if not block.is_available:
                return JsonResponse({'success': False, 'error': f'Session at {block.date} {block.start_time} is no longer available'})

            # Check if block has session types
            catalog_types = list(block.catalog_session_types.all())
            if not catalog_types:
                return JsonResponse({'success': False, 'error': 'Session block has no session type configured'})

            # Check if free session
            is_free = (
                block.price_override is not None and block.price_override == 0
            ) or all(
                (st.drop_in_price is not None and st.drop_in_price == 0) or (st.price == 0 and not st.requires_package)
                for st in catalog_types
            )

            # Determine if this session type allows package usage
            session_type = catalog_types[0]
            allows_package = session_type.allow_package
            drop_in_price = session_type.drop_in_price or session_type.price or block.price_override

            # Validate package or require payment
            pkg = None
            requires_payment = False

            if not is_free:
                if allows_package:
                    pkg = get_package_for_player(player, session_type)
                    if pkg and pkg.package.sessions_included > 0:
                        # Account for sessions already claimed in this batch
                        batch_used = package_sessions_used.get(pkg.id, 0)
                        if pkg.sessions_remaining - batch_used <= 0:
                            pkg = None  # Package exhausted (including batch claims)

                    if pkg:
                        # Reserve one session in this batch
                        package_sessions_used[pkg.id] = package_sessions_used.get(pkg.id, 0) + 1
                    else:
                        requires_payment = True
                else:
                    # Session type doesn't allow packages — always requires payment
                    requires_payment = True

            validated_bookings.append({
                'block': block,
                'player': player,
                'package': pkg,
                'is_free': is_free,
                'session_type': session_type,
                'requires_payment': requires_payment,
                'price': block.price_override if block.price_override is not None else drop_in_price,
            })

        # Separate items requiring payment from those covered by package/free
        payment_items = [i for i in validated_bookings if i['requires_payment']]
        covered_items = [i for i in validated_bookings if not i['requires_payment']]

        # Always create bookings for covered items (package/free) immediately
        created_bookings = []
        for item in covered_items:
            booking = Booking.objects.create(
                client=client,
                player=item['player'],
                coach=item['block'].coach,
                session_type=item['session_type'],
                scheduled_date=item['block'].date,
                scheduled_time=item['block'].start_time,
                client_package=item['package'],
                status='confirmed',
                payment_status='package' if item['package'] else 'paid',
            )

            # Deduct session from package (refresh to avoid stale state in batch)
            if item['package']:
                item['package'].refresh_from_db()
                item['package'].use_session()

            # Update block availability
            item['block'].current_participants += 1
            if item['block'].current_participants >= item['block'].max_participants:
                item['block'].status = 'booked'
            item['block'].save()

            created_bookings.append(booking)

            # Queue notification
            try:
                from clients.notification_utils import queue_grouped_notification
                queue_grouped_notification(
                    client=client,
                    event_type='booking_confirmed',
                    context={'booking_id': booking.id, 'payment_method': 'free' if item['is_free'] else 'package'},
                    group_key=f'booking_{booking.id}',
                    window_seconds=30,
                )
            except Exception:
                pass

        # If some items require payment, return payment info alongside confirmed bookings
        if payment_items:
            # Sibling discount: 2nd+ player from the same client booked into the same block pays 50%.
            # Track which blocks already have a full-price entry in this batch.
            _full_price_blocks: set = set()
            pending_payment = []
            for item in payment_items:
                block_id = item['block'].id
                price = item['price']
                if price and price > 0:
                    if block_id in _full_price_blocks:
                        # Sibling — 50% off
                        from decimal import Decimal
                        price = (Decimal(str(price)) * Decimal('50') / Decimal('100')).quantize(Decimal('0.01'))
                    else:
                        _full_price_blocks.add(block_id)
                pending_payment.append({
                    'block_id': block_id,
                    'player_id': item['player'].id,
                    'amount': str(price),
                    'session_type': item['session_type'].name,
                    'player_name': f"{item['player'].first_name} {item['player'].last_name}",
                })

            return JsonResponse({
                'success': True,
                'requires_payment': True,
                'bookings_created': len(created_bookings),
                'pending_payment': pending_payment,
            })

        return JsonResponse({
            'success': True,
            'bookings_created': len(created_bookings),
            'booking_ids': [b.id for b in created_bookings]
        })

    except Exception as e:
        logger.exception('create_booking_direct failed')
        return JsonResponse({'success': False, 'error': f'Booking failed: {str(e)}'})
