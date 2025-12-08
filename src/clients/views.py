from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Client, Player, Package, ClientPackage, NotificationPreference, Notification, SessionReservation, BookingPreference
from bookings.models import Booking, Program
from coaches.models import PlayerAssessment, Coach, ScheduleBlock


@login_required
def dashboard(request):
    """Main client dashboard view."""
    # Get or create client profile
    client, created = Client.objects.get_or_create(user=request.user)

    # Get client's players
    players = client.players.filter(is_active=True)

    # Get active packages
    active_packages = client.packages.filter(
        status='active',
        expiry_date__gte=timezone.now().date()
    )

    # Get upcoming bookings
    upcoming_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__gte=timezone.now().date(),
        status__in=['pending', 'confirmed']
    ).select_related('player', 'program', 'coach').order_by('scheduled_date', 'scheduled_time')[:5]

    # Get recent bookings (past)
    past_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__lt=timezone.now().date()
    ).select_related('player', 'program', 'coach').order_by('-scheduled_date', '-scheduled_time')[:5]

    context = {
        'client': client,
        'players': players,
        'active_packages': active_packages,
        'upcoming_bookings': upcoming_bookings,
        'past_bookings': past_bookings,
    }
    return render(request, 'clients/dashboard.html', context)


@login_required
def profile(request):
    """View and edit client profile."""
    client, created = Client.objects.get_or_create(user=request.user)
    booking_prefs, _ = BookingPreference.objects.get_or_create(client=client)
    coaches = Coach.objects.filter(is_active=True)

    if request.method == 'POST':
        # Update user info
        request.user.first_name = request.POST.get('first_name', '')
        request.user.last_name = request.POST.get('last_name', '')
        request.user.save()

        # Update client info
        client.phone = request.POST.get('phone', '')
        client.address = request.POST.get('address', '')
        client.emergency_contact = request.POST.get('emergency_contact', '')
        client.emergency_phone = request.POST.get('emergency_phone', '')
        client.client_type = request.POST.get('client_type', 'parent')
        client.save()

        # Update booking preferences
        favorite_coach_ids = request.POST.getlist('favorite_coaches')
        booking_prefs.favorite_coaches.set(favorite_coach_ids)
        booking_prefs.preferred_days = request.POST.getlist('preferred_days')
        booking_prefs.preferred_time_slots = request.POST.getlist('preferred_time_slots')
        booking_prefs.auto_filter = request.POST.get('auto_filter') == 'on'
        booking_prefs.save()

        messages.success(request, 'Profile updated successfully!')
        return redirect('clients:profile')

    context = {
        'client': client,
        'booking_prefs': booking_prefs,
        'coaches': coaches,
        'client_types': Client.CLIENT_TYPE_CHOICES,
        'day_choices': BookingPreference.DAY_CHOICES,
        'time_slot_choices': BookingPreference.TIME_SLOT_CHOICES,
    }
    return render(request, 'clients/profile.html', context)


@login_required
def players_list(request):
    """List all players for the client."""
    client, created = Client.objects.get_or_create(user=request.user)
    players = client.players.all()

    context = {
        'client': client,
        'players': players,
    }
    return render(request, 'clients/players.html', context)


@login_required
def player_add(request):
    """Add a new player."""
    client, created = Client.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        player = Player.objects.create(
            client=client,
            first_name=request.POST.get('first_name', ''),
            last_name=request.POST.get('last_name', ''),
            birth_year=int(request.POST.get('birth_year', timezone.now().year - 10)),
            gender=request.POST.get('gender', 'O'),
            soccer_club=request.POST.get('soccer_club', ''),
            team_name=request.POST.get('team_name', ''),
            skill_level=request.POST.get('skill_level', 'beginner'),
            primary_position=request.POST.get('primary_position', ''),
            notes=request.POST.get('notes', ''),
        )
        if request.FILES.get('photo'):
            player.photo = request.FILES['photo']
            player.save()
        messages.success(request, f'{player.first_name} has been added!')
        return redirect('clients:players')

    context = {
        'skill_levels': Player.SKILL_LEVEL_CHOICES,
        'positions': Player.POSITION_CHOICES,
        'genders': Player.GENDER_CHOICES,
    }
    return render(request, 'clients/player_form.html', context)


@login_required
def player_edit(request, player_id):
    """Edit an existing player."""
    client, created = Client.objects.get_or_create(user=request.user)
    player = get_object_or_404(Player, id=player_id, client=client)

    if request.method == 'POST':
        player.first_name = request.POST.get('first_name', player.first_name)
        player.last_name = request.POST.get('last_name', player.last_name)
        player.birth_year = int(request.POST.get('birth_year', player.birth_year))
        player.gender = request.POST.get('gender', player.gender)
        player.soccer_club = request.POST.get('soccer_club', '')
        player.team_name = request.POST.get('team_name', '')
        player.skill_level = request.POST.get('skill_level', player.skill_level)
        player.primary_position = request.POST.get('primary_position', '')
        player.notes = request.POST.get('notes', '')
        if request.FILES.get('photo'):
            player.photo = request.FILES['photo']
        player.save()

        messages.success(request, f'{player.first_name}\'s profile has been updated!')
        return redirect('clients:players')

    context = {
        'player': player,
        'skill_levels': Player.SKILL_LEVEL_CHOICES,
        'positions': Player.POSITION_CHOICES,
        'genders': Player.GENDER_CHOICES,
    }
    return render(request, 'clients/player_form.html', context)


@login_required
@require_POST
def player_delete(request, player_id):
    """Delete (deactivate) a player."""
    client, created = Client.objects.get_or_create(user=request.user)
    player = get_object_or_404(Player, id=player_id, client=client)

    player.is_active = False
    player.save()

    messages.success(request, f'{player.first_name} has been removed.')
    return redirect('clients:players')


@login_required
def packages_list(request):
    """List all packages for the client."""
    client, created = Client.objects.get_or_create(user=request.user)

    active_packages = client.packages.filter(
        status='active',
        expiry_date__gte=timezone.now().date()
    )

    expired_packages = client.packages.exclude(
        status='active',
        expiry_date__gte=timezone.now().date()
    )

    # Available packages for purchase
    available_packages = Package.objects.filter(is_active=True)

    context = {
        'client': client,
        'active_packages': active_packages,
        'expired_packages': expired_packages,
        'available_packages': available_packages,
    }
    return render(request, 'clients/packages.html', context)


@login_required
def bookings_list(request):
    """List all bookings for the client."""
    client, created = Client.objects.get_or_create(user=request.user)

    upcoming_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__gte=timezone.now().date(),
        status__in=['pending', 'confirmed']
    ).select_related('player', 'program', 'coach').order_by('scheduled_date', 'scheduled_time')

    past_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__lt=timezone.now().date()
    ).select_related('player', 'program', 'coach').order_by('-scheduled_date', '-scheduled_time')

    context = {
        'client': client,
        'upcoming_bookings': upcoming_bookings,
        'past_bookings': past_bookings,
    }
    return render(request, 'clients/bookings.html', context)


@login_required
@require_POST
def booking_cancel(request, booking_id):
    """Cancel a booking."""
    client, created = Client.objects.get_or_create(user=request.user)
    booking = get_object_or_404(Booking, id=booking_id, client=client)

    if booking.status in ['pending', 'confirmed']:
        booking.status = 'cancelled'
        booking.save()

        # Restore session to package if applicable
        if booking.client_package:
            booking.client_package.sessions_remaining += 1
            booking.client_package.sessions_used -= 1
            if booking.client_package.status == 'exhausted':
                booking.client_package.status = 'active'
            booking.client_package.save()

        messages.success(request, 'Booking has been cancelled.')
    else:
        messages.error(request, 'This booking cannot be cancelled.')

    return redirect('clients:bookings')


@login_required
def notification_settings(request):
    """Manage notification preferences."""
    client, created = Client.objects.get_or_create(user=request.user)
    prefs, created = NotificationPreference.objects.get_or_create(client=client)

    if request.method == 'POST':
        prefs.booking_confirmations = request.POST.get('booking_confirmations', 'email')
        prefs.booking_reminders = request.POST.get('booking_reminders', 'email')
        prefs.booking_cancellations = request.POST.get('booking_cancellations', 'email')
        prefs.purchase_confirmations = request.POST.get('purchase_confirmations', 'email')
        prefs.assessment_notifications = request.POST.get('assessment_notifications', 'email')
        prefs.promotional_updates = request.POST.get('promotional_updates', 'none')
        prefs.reminder_hours_before = int(request.POST.get('reminder_hours_before', 24))
        prefs.save()

        messages.success(request, 'Notification preferences updated!')
        return redirect('clients:notification_settings')

    context = {
        'client': client,
        'prefs': prefs,
        'method_choices': NotificationPreference.NOTIFICATION_METHOD_CHOICES,
    }
    return render(request, 'clients/notifications.html', context)


@login_required
def assessments_view(request):
    """View player assessments received from coaches."""
    client, created = Client.objects.get_or_create(user=request.user)
    players = client.players.filter(is_active=True)

    # Get all assessments for client's players
    assessments = PlayerAssessment.objects.filter(
        player__client=client
    ).select_related('player', 'coach', 'booking__program').order_by('-assessment_date')

    context = {
        'client': client,
        'assessments': assessments,
    }
    return render(request, 'clients/assessments.html', context)


@login_required
def booking_page(request):
    """Main booking page with package info and session selection."""
    client, created = Client.objects.get_or_create(user=request.user)
    booking_prefs, _ = BookingPreference.objects.get_or_create(client=client)

    # Clean up expired reservations
    SessionReservation.cleanup_expired()

    # Get client's active package
    active_package = client.packages.filter(
        status='active',
        expiry_date__gte=timezone.now().date()
    ).first()

    # Get players
    players = client.players.filter(is_active=True)

    # Get coaches
    coaches = Coach.objects.filter(is_active=True)

    # Get programs
    programs = Program.objects.filter(is_active=True)

    # Get available schedule blocks (next 30 days)
    today = timezone.now().date()
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
        is_active=True,
        is_special=False
    ).exclude(package_type='team').order_by('price')

    # Special event packages (always shown)
    special_packages = Package.objects.filter(
        is_active=True,
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

    # Get favorite coach IDs for template
    favorite_coach_ids = list(booking_prefs.favorite_coaches.values_list('id', flat=True))

    # Get blocked dates from special packages (dates when special events are happening)
    blocked_dates = []
    for sp in special_packages:
        if sp.event_start_date and sp.event_end_date:
            current = sp.event_start_date
            while current <= sp.event_end_date:
                blocked_dates.append(current.isoformat())
                current += timedelta(days=1)

    context = {
        'client': client,
        'active_package': active_package,
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
    }
    return render(request, 'clients/booking.html', context)


@login_required
@require_POST
def reserve_session(request):
    """Reserve a session slot (temporary hold for 10 minutes)."""
    client, created = Client.objects.get_or_create(user=request.user)

    block_id = request.POST.get('block_id')
    player_id = request.POST.get('player_id')

    block = get_object_or_404(ScheduleBlock, id=block_id)
    player = get_object_or_404(Player, id=player_id, client=client)

    # Check if block is still available
    if not block.is_available:
        return JsonResponse({'success': False, 'error': 'Session is no longer available'})

    # Check if client has an active package with sessions remaining
    active_package = client.packages.filter(
        status='active',
        expiry_date__gte=timezone.now().date()
    ).first()

    if not active_package or (active_package.package.sessions_included > 0 and active_package.sessions_remaining <= 0):
        return JsonResponse({'success': False, 'error': 'No available sessions in your package'})

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

    # Get active package
    active_package = client.packages.filter(
        status='active',
        expiry_date__gte=timezone.now().date()
    ).first()

    if not active_package:
        return JsonResponse({'success': False, 'error': 'No active package'})

    # Check if enough sessions remain
    if active_package.package.sessions_included > 0:
        if active_package.sessions_remaining < reservations.count():
            return JsonResponse({
                'success': False,
                'error': f'Only {active_package.sessions_remaining} sessions remaining in your package'
            })

    # Get program (default to first active program for now)
    program = Program.objects.filter(is_active=True).first()

    bookings_created = 0
    for reservation in reservations:
        # Create the booking
        booking = Booking.objects.create(
            client=client,
            player=reservation.player,
            coach=reservation.schedule_block.coach,
            program=program,
            scheduled_date=reservation.schedule_block.date,
            scheduled_time=reservation.schedule_block.start_time,
            client_package=active_package,
            status='confirmed'
        )

        # Use a session from the package
        active_package.use_session()

        # Mark reservation as confirmed
        reservation.is_confirmed = True
        reservation.save()

        bookings_created += 1

    return JsonResponse({
        'success': True,
        'bookings_created': bookings_created,
        'sessions_remaining': active_package.sessions_remaining
    })
