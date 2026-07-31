from django.shortcuts import render, redirect
from django.urls import reverse
from django.db.models import Sum, Q
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone

from clients.models import Client, Player, Package, ClientPackage, NotificationPreference, Notification, SessionReservation, BookingPreference, PushSubscription, Team, FieldRentalSlot, ClientWaiver, get_current_waiver, DiscountCode, UnsubscribeToken
from bookings.models import Booking, Program, AvailabilitySlot
from coaches.models import PlayerAssessment, Coach, ScheduleBlock
from clients.utils import validate_photo as _validate_photo, _MAX_PHOTO_BYTES, _ALLOWED_PHOTO_EXTENSIONS


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
        expiry_date__gte=timezone.localdate()
    )

    # Get upcoming bookings — exclude orphaned pending-payment bookings from old paid flow,
    # but only when the session type has a non-zero price (free/comp sessions are always shown).
    upcoming_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__gte=timezone.localdate(),
        status__in=['pending', 'confirmed']
    ).exclude(
        payment_status='pending', client_package__isnull=True, session_type__price__gt=0
    ).select_related('player', 'session_type', 'coach').order_by('scheduled_date', 'scheduled_time')[:5]

    # Get recent bookings (past)
    past_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__lt=timezone.localdate()
    ).select_related('player', 'session_type', 'coach').order_by('-scheduled_date', '-scheduled_time')[:5]

    # Total sessions remaining across all active packages
    sessions_remaining_total = sum(
        p.sessions_remaining for p in active_packages if p.package.sessions_included > 0
    )
    has_unlimited = active_packages.filter(package__sessions_included=0).exists()

    # All-time completed sessions count
    sessions_completed_total = Booking.objects.filter(
        client=client, status__in=['completed', 'cancelled', 'no_show']
    ).count()

    # Next upcoming booking (for same-day reminder)
    today = timezone.localdate()
    today_dt = timezone.now()
    next_booking = upcoming_bookings.first()
    next_booking_soon = None
    if next_booking and next_booking.scheduled_date == today:
        import datetime as dt
        next_dt = dt.datetime.combine(next_booking.scheduled_date, next_booking.scheduled_time)
        next_dt = timezone.make_aware(next_dt) if timezone.is_naive(next_dt) else next_dt
        if (next_dt - today_dt).total_seconds() > 0:
            next_booking_soon = next_booking

    # Packages expiring soon (within 14 days)
    expiring_soon = [
        p for p in active_packages
        if (p.expiry_date - today).days <= 14
    ]

    # Active packages with no player assigned
    unassigned_packages = [p for p in active_packages if not p.player_id]
    single_player = players.first() if unassigned_packages and players.count() == 1 else None

    from clients.services import _booking_location, _location_map_url
    for b in upcoming_bookings:
        b.effective_location = _booking_location(b)
        b.effective_location_map_url = _location_map_url(b.effective_location)

    # APC Select membership
    from django.db.models import Q, Sum
    select_pkg = active_packages.filter(package__package_type='select').select_related('package').first()
    has_select_membership = select_pkg is not None
    select_credit_balance = client.credits.filter(
        status='available'
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=today)
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Select team, practice counter, and upcoming game RSVPs
    select_team = None
    select_practices_this_month = 0
    select_practices_remaining = 2
    upcoming_game_rsvps = []
    if has_select_membership:
        from bookings.models import Booking as _Booking, SessionType as _ST, SelectGameRSVP
        month_start = today.replace(day=1)
        select_practice_type_ids = list(
            _ST.objects.filter(session_format='select_practice', is_active=True).values_list('id', flat=True)
        )
        # Combine across all active players for this client
        select_practices_this_month = _Booking.objects.filter(
            client=client,
            session_type_id__in=select_practice_type_ids,
            status='confirmed',
            scheduled_date__gte=month_start,
        ).count()
        select_practices_remaining = max(0, 2 - select_practices_this_month)

        # Select team from any active player's primary team
        active_players = client.players.filter(is_active=True).select_related('team')
        for p in active_players:
            if p.team and p.team.is_select:
                select_team = p.team
                break

        # Upcoming game RSVPs for this client
        upcoming_game_rsvps = SelectGameRSVP.objects.filter(
            client=client,
            game__date__gte=today,
            game__status='published',
        ).select_related('game__team').order_by('game__date', 'game__start_time')

    context = {
        'client': client,
        'players': players,
        'active_packages': active_packages,
        'upcoming_bookings': upcoming_bookings,
        'past_bookings': past_bookings,
        'sessions_remaining_total': sessions_remaining_total,
        'has_unlimited': has_unlimited,
        'sessions_completed_total': sessions_completed_total,
        'next_booking_soon': next_booking_soon,
        'expiring_soon': expiring_soon,
        'unassigned_packages': unassigned_packages,
        'single_player': single_player,
        'has_select_membership': has_select_membership,
        'select_credit_balance': select_credit_balance,
        'select_pkg': select_pkg,
        'select_team': select_team,
        'select_practices_this_month': select_practices_this_month,
        'select_practices_remaining': select_practices_remaining,
        'upcoming_game_rsvps': upcoming_game_rsvps,
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
        old_type = client.client_type
        new_type = request.POST.get('client_type', 'parent')
        client.phone = request.POST.get('phone', '')
        client.address = request.POST.get('address', '')
        client.emergency_contact = request.POST.get('emergency_contact', '')
        client.emergency_phone = request.POST.get('emergency_phone', '')
        client.client_type = new_type

        # Trigger approval workflow when switching to coach or renter
        if new_type in ('coach', 'renter') and old_type != new_type:
            client.approval_status = 'pending'
            # Notify owner
            from django.contrib.auth.models import User as AuthUser
            type_label = dict(Client.CLIENT_TYPE_CHOICES).get(new_type, new_type)
            owner_users = AuthUser.objects.filter(groups__name='Owner')
            for owner in owner_users:
                if hasattr(owner, 'client'):
                    owner_client = owner.client
                else:
                    continue
                Notification.objects.create(
                    client=owner_client,
                    notification_type='promotional',
                    title=f'Approval Required: {client} — {type_label}',
                    message=f'{client.user.get_full_name() or client.user.username} has requested {type_label} access and is pending your approval.\n\nReview in the Owner Portal → Clients → {client}.',
                    method='email',
                )
        elif new_type == 'parent' and old_type in ('coach', 'renter'):
            # Switching back to parent — reset approval
            client.approval_status = 'not_required'

        client.save()

        # Update booking preferences
        favorite_coach_ids = request.POST.getlist('favorite_coaches')
        booking_prefs.favorite_coaches.set(favorite_coach_ids)
        booking_prefs.preferred_days = request.POST.getlist('preferred_days')
        booking_prefs.preferred_time_slots = request.POST.getlist('preferred_time_slots')
        booking_prefs.auto_filter = request.POST.get('auto_filter') == 'on'
        booking_prefs.save()

        # Athlete (18+) — create/update their self-player record
        if client.client_type == 'athlete':
            birth_year_str = request.POST.get('athlete_birth_year', '').strip()
            if birth_year_str.isdigit():
                self_player, _ = Player.objects.get_or_create(
                    client=client,
                    is_self=True,
                    defaults={
                        'first_name': request.user.first_name or request.user.username,
                        'last_name': request.user.last_name,
                        'birth_year': int(birth_year_str),
                        'gender': request.POST.get('athlete_gender', 'O'),
                    }
                )
                self_player.first_name  = request.user.first_name or request.user.username
                self_player.last_name   = request.user.last_name
                self_player.birth_year  = int(birth_year_str)
                self_player.gender      = request.POST.get('athlete_gender', self_player.gender)
                self_player.skill_level = request.POST.get('athlete_skill_level', self_player.skill_level)
                self_player.primary_position = request.POST.get('athlete_primary_position', self_player.primary_position)
                self_player.soccer_club = request.POST.get('athlete_soccer_club', self_player.soccer_club)
                self_player.team_name   = request.POST.get('athlete_team_name', self_player.team_name)
                self_player.notes       = request.POST.get('athlete_notes', self_player.notes)
                self_player.is_active   = True
                self_player.save()

        # Server-side required field validation
        missing = []
        if not request.user.first_name: missing.append('First name')
        if not request.user.last_name:  missing.append('Last name')
        if not request.POST.get('phone', '').strip(): missing.append('Phone number')
        if not request.POST.get('emergency_contact', '').strip(): missing.append('Emergency contact name')
        if not request.POST.get('emergency_phone', '').strip(): missing.append('Emergency contact phone')
        if missing:
            messages.error(request, f'Required fields missing: {", ".join(missing)}')
            return redirect('clients:profile')

        messages.success(request, 'Profile updated successfully!')
        return redirect('clients:profile')

    current_waiver = get_current_waiver(client)
    athlete_player = client.players.filter(is_self=True, is_active=True).first() if client.client_type == 'athlete' else None
    context = {
        'client': client,
        'booking_prefs': booking_prefs,
        'coaches': coaches,
        'client_types': Client.CLIENT_TYPE_CHOICES,
        'day_choices': BookingPreference.DAY_CHOICES,
        'time_slot_choices': BookingPreference.TIME_SLOT_CHOICES,
        'current_waiver': current_waiver,
        'waiver_version': ClientWaiver.WAIVER_VERSION,
        'waiver_year': timezone.now().year,
        'athlete_player': athlete_player,
        'skill_levels': Player.SKILL_LEVEL_CHOICES,
        'positions': Player.POSITION_CHOICES,
        'genders': Player.GENDER_CHOICES,
    }
    return render(request, 'clients/profile.html', context)


@login_required
@require_POST
def sign_waiver(request):
    """Process digital waiver signature."""
    client, _ = Client.objects.get_or_create(user=request.user)

    # Already signed this year?
    if get_current_waiver(client):
        messages.info(request, 'You have already signed the waiver for this year.')
        return redirect('clients:profile')

    full_name      = request.POST.get('waiver_full_name', '').strip()
    signature_text = request.POST.get('waiver_signature', '').strip()
    guardian_name  = request.POST.get('guardian_name', '').strip()
    photo_consent  = request.POST.get('photo_video_consent') == 'on'
    agreed         = request.POST.get('agree_terms') == 'on'

    if not agreed or not full_name or not signature_text:
        messages.error(request, 'Please read the waiver, fill in your name and typed signature, and check the agreement box.')
        return redirect('clients:profile')

    # Capture IP for audit
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    ip = x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR')

    ClientWaiver.objects.create(
        client=client,
        full_name=full_name,
        signature_text=signature_text,
        guardian_name=guardian_name,
        photo_video_consent=photo_consent,
        waiver_version=ClientWaiver.WAIVER_VERSION,
        valid_year=timezone.now().year,
        ip_address=ip,
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
    )
    messages.success(request, f'Waiver signed successfully. Valid through December 31, {timezone.now().year}.')
    return redirect('clients:profile')
