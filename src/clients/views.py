from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Client, Player, Package, ClientPackage, NotificationPreference, Notification, SessionReservation, BookingPreference, PushSubscription, Team, FieldRentalSlot, ClientWaiver, get_current_waiver
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
    ).select_related('player', 'session_type', 'coach').order_by('scheduled_date', 'scheduled_time')[:5]

    # Get recent bookings (past)
    past_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__lt=timezone.now().date()
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

    # Next upcoming booking (for 24h reminder)
    today_dt = timezone.now()
    next_booking = upcoming_bookings.first()
    next_booking_soon = None
    if next_booking:
        import datetime as dt
        next_dt = dt.datetime.combine(next_booking.scheduled_date, next_booking.scheduled_time)
        next_dt = timezone.make_aware(next_dt) if timezone.is_naive(next_dt) else next_dt
        hours_away = (next_dt - today_dt).total_seconds() / 3600
        if 0 < hours_away <= 24:
            next_booking_soon = next_booking

    # Packages expiring soon (within 14 days)
    today = timezone.now().date()
    expiring_soon = [
        p for p in active_packages
        if (p.expiry_date - today).days <= 14
    ]

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
            school_grade=request.POST.get('school_grade', ''),
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
        'grades': Player.GRADE_CHOICES,
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
        player.school_grade = request.POST.get('school_grade', '')
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
        'grades': Player.GRADE_CHOICES,
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
@require_POST
def package_payment_intent(request, package_id):
    """Proxy to payments app — create PaymentIntent for one-time package purchase."""
    from payments.views import create_package_payment_intent
    return create_package_payment_intent(request, package_id)


@login_required
@require_POST
def package_subscribe(request, package_id):
    """Proxy to payments app — create Stripe Subscription for recurring package."""
    from payments.views import create_package_subscription
    return create_package_subscription(request, package_id)


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

    # Separate select membership from regular packages
    select_packages = Package.objects.filter(is_active=True, is_purchasable=True, package_type='select').order_by('price')
    available_packages = Package.objects.filter(
        is_active=True, is_purchasable=True, is_special=False
    ).exclude(package_type__in=['team', 'select']).order_by('price')
    special_packages = Package.objects.filter(
        is_active=True, is_purchasable=True, is_special=True
    ).order_by('event_start_date')

    has_select_membership = active_packages.filter(package__package_type='select').exists()
    select_credit_balance = sum(
        c.amount for c in client.credits.filter(status='available') if c.is_usable
    ) if has_select_membership else 0

    from django.conf import settings as django_settings
    context = {
        'client': client,
        'active_packages': active_packages,
        'expired_packages': expired_packages,
        'available_packages': available_packages,
        'special_packages': special_packages,
        'select_packages': select_packages,
        'has_select_membership': has_select_membership,
        'select_credit_balance': select_credit_balance,
        'stripe_public_key': django_settings.STRIPE_PUBLIC_KEY,
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
    ).select_related('player', 'session_type', 'coach').order_by('scheduled_date', 'scheduled_time')

    past_bookings = Booking.objects.filter(
        client=client,
        scheduled_date__lt=timezone.now().date()
    ).select_related('player', 'session_type', 'coach').order_by('-scheduled_date', '-scheduled_time')

    from django.conf import settings as django_settings
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
def notification_history(request):
    """View notification history."""
    client, created = Client.objects.get_or_create(user=request.user)

    notifications = Notification.objects.filter(
        client=client
    ).order_by('-created_at')[:50]

    # Mark unread notifications as read
    unread = notifications.filter(status='sent', read_at__isnull=True)
    unread.update(status='read', read_at=timezone.now())

    context = {
        'client': client,
        'notifications': notifications,
    }
    return render(request, 'clients/notification_history.html', context)


@login_required
@require_POST
def register_push_subscription(request):
    """Register a web push notification subscription."""
    import json
    client, created = Client.objects.get_or_create(user=request.user)

    try:
        data = json.loads(request.body)
        endpoint = data.get('endpoint')
        keys = data.get('keys', {})

        if not endpoint or not keys.get('p256dh') or not keys.get('auth'):
            return JsonResponse({'error': 'Invalid subscription data'}, status=400)

        # Create or update subscription
        subscription, created = PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                'client': client,
                'p256dh_key': keys['p256dh'],
                'auth_key': keys['auth'],
                'user_agent': request.META.get('HTTP_USER_AGENT', '')[:255],
                'is_active': True,
            }
        )

        return JsonResponse({
            'success': True,
            'created': created,
            'message': 'Push notifications enabled!'
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def unregister_push_subscription(request):
    """Unregister a web push notification subscription."""
    import json
    client, created = Client.objects.get_or_create(user=request.user)

    try:
        data = json.loads(request.body)
        endpoint = data.get('endpoint')

        if endpoint:
            PushSubscription.objects.filter(
                client=client,
                endpoint=endpoint
            ).update(is_active=False)

        return JsonResponse({'success': True, 'message': 'Push notifications disabled'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def get_unread_count(request):
    """Get count of unread notifications for badge display."""
    client, created = Client.objects.get_or_create(user=request.user)

    count = Notification.objects.filter(
        client=client,
        status='sent',
        read_at__isnull=True
    ).count()

    return JsonResponse({'unread_count': count})


@login_required
def assessments_view(request):
    """View player assessments received from coaches."""
    client, created = Client.objects.get_or_create(user=request.user)
    players = client.players.filter(is_active=True)

    # Get all assessments for client's players
    assessments = PlayerAssessment.objects.filter(
        player__client=client
    ).select_related('player', 'coach', 'booking__session_type').order_by('-assessment_date')

    context = {
        'client': client,
        'assessments': assessments,
    }
    return render(request, 'clients/assessments.html', context)


@login_required
def player_assessments(request, player_id):
    """View assessments for a specific player with time series chart."""
    from django.db.models import Avg
    client, created = Client.objects.get_or_create(user=request.user)
    player = get_object_or_404(Player, id=player_id, client=client)

    # Get all assessments for this player
    assessments_qs = PlayerAssessment.objects.filter(
        player=player
    ).select_related('coach', 'booking__session_type').order_by('-assessment_date')

    # Convert to list and add calculated overall rating
    assessments = []
    for a in assessments_qs:
        a.calc_overall = (a.effort_engagement + a.technical_proficiency +
                         a.tactical_awareness + a.physical_performance +
                         a.goals_achievement) / 5.0
        assessments.append(a)

    # Calculate averages for summary
    if assessments:
        averages = assessments_qs.aggregate(
            avg_effort=Avg('effort_engagement'),
            avg_technical=Avg('technical_proficiency'),
            avg_tactical=Avg('tactical_awareness'),
            avg_physical=Avg('physical_performance'),
            avg_goals=Avg('goals_achievement'),
        )
        # Calculate overall as average of all metrics
        if all(v is not None for v in averages.values()):
            averages['avg_overall'] = sum(averages.values()) / 5
        else:
            averages['avg_overall'] = None
    else:
        averages = {}

    context = {
        'client': client,
        'player': player,
        'assessments': assessments,
        'averages': averages,
        'total_assessments': len(assessments),
    }
    return render(request, 'clients/player_assessments.html', context)


@login_required
def player_assessment_chart_data(request, player_id):
    """API endpoint for player assessment chart data."""
    import json
    client, created = Client.objects.get_or_create(user=request.user)
    player = get_object_or_404(Player, id=player_id, client=client)

    # Get date range from query params
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    assessments = PlayerAssessment.objects.filter(player=player)

    if date_from:
        assessments = assessments.filter(assessment_date__gte=date_from)
    if date_to:
        assessments = assessments.filter(assessment_date__lte=date_to)

    assessments = assessments.order_by('assessment_date')

    # Build chart data
    data = {
        'labels': [],
        'datasets': {
            'overall': [],
            'effort': [],
            'technical': [],
            'tactical': [],
            'physical': [],
            'goals': [],
        }
    }

    for assessment in assessments:
        data['labels'].append(assessment.assessment_date.strftime('%b %d, %Y'))
        # Calculate overall as average of all 5 metrics
        overall = (assessment.effort_engagement + assessment.technical_proficiency +
                   assessment.tactical_awareness + assessment.physical_performance +
                   assessment.goals_achievement) / 5
        data['datasets']['overall'].append(round(overall, 2))
        data['datasets']['effort'].append(assessment.effort_engagement)
        data['datasets']['technical'].append(assessment.technical_proficiency)
        data['datasets']['tactical'].append(assessment.tactical_awareness)
        data['datasets']['physical'].append(assessment.physical_performance)
        data['datasets']['goals'].append(assessment.goals_achievement)

    return JsonResponse(data)


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
    select_credit_balance = sum(
        c.amount for c in client.credits.filter(status='available')
        if c.is_usable
    ) if has_select_membership else 0

    # Get favorite coach IDs for template
    favorite_coach_ids = list(booking_prefs.favorite_coaches.values_list('id', flat=True))

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


# ============================================================================
# TEAM MANAGEMENT VIEWS (for Team Coaches)
# ============================================================================

@login_required
def team_list(request):
    """List all teams managed by the coach client."""
    client, created = Client.objects.get_or_create(user=request.user)
    
    # Only team coaches can access team features
    if client.client_type != 'coach':
        messages.error(request, 'Team features are only available for team coaches.')
        return redirect('clients:dashboard')
    
    teams = client.managed_teams.filter(is_active=True)
    
    context = {
        'client': client,
        'teams': teams,
    }
    return render(request, 'clients/team_list.html', context)


@login_required
def team_create(request):
    """Create a new team."""
    client, created = Client.objects.get_or_create(user=request.user)
    
    if client.client_type != 'coach':
        messages.error(request, 'Only team coaches can create teams.')
        return redirect('clients:dashboard')
    
    if request.method == 'POST':
        from django.utils.text import slugify
        
        team = Team.objects.create(
            manager=client,
            name=request.POST.get('name', ''),
            slug=slugify(request.POST.get('name', '')),
            age_group=request.POST.get('age_group', ''),
            skill_level=request.POST.get('skill_level', 'intermediate'),
            club_name=request.POST.get('club_name', ''),
            description=request.POST.get('description', ''),
            max_players=int(request.POST.get('max_players', 18)),
        )
        
        # Assign coaches if selected
        coach_ids = request.POST.getlist('coaches')
        if coach_ids:
            team.coaches.set(coach_ids)
        
        messages.success(request, f'Team "{team.name}" has been created!')
        return redirect('clients:team_detail', team_id=team.id)
    
    coaches = Coach.objects.filter(is_active=True)
    context = {
        'client': client,
        'coaches': coaches,
        'skill_levels': Player.SKILL_LEVEL_CHOICES,
    }
    return render(request, 'clients/team_form.html', context)


@login_required
def team_detail(request, team_id):
    """View team details and roster."""
    client, created = Client.objects.get_or_create(user=request.user)
    team = get_object_or_404(Team, id=team_id, manager=client, is_active=True)
    
    players = team.players.filter(is_active=True)
    coaches = team.coaches.all()
    
    # Get team's upcoming bookings
    upcoming_bookings = Booking.objects.filter(
        player__team=team,
        scheduled_date__gte=timezone.now().date(),
        status__in=['pending', 'confirmed']
    ).select_related('player', 'coach').order_by('scheduled_date', 'scheduled_time')
    
    # Check for active team package
    active_package = client.packages.filter(
        status='active',
        package__package_type='team',
        expiry_date__gte=timezone.now().date()
    ).first()
    
    context = {
        'client': client,
        'team': team,
        'players': players,
        'coaches': coaches,
        'upcoming_bookings': upcoming_bookings,
        'active_package': active_package,
        'available_slots': active_package.sessions_remaining if active_package else 0,
    }
    return render(request, 'clients/team_detail.html', context)


@login_required
def team_edit(request, team_id):
    """Edit team details."""
    client, created = Client.objects.get_or_create(user=request.user)
    team = get_object_or_404(Team, id=team_id, manager=client)
    
    if request.method == 'POST':
        team.name = request.POST.get('name', team.name)
        team.age_group = request.POST.get('age_group', team.age_group)
        team.skill_level = request.POST.get('skill_level', team.skill_level)
        team.club_name = request.POST.get('club_name', team.club_name)
        team.description = request.POST.get('description', team.description)
        team.max_players = int(request.POST.get('max_players', team.max_players))
        
        # Update coaches
        coach_ids = request.POST.getlist('coaches')
        team.coaches.set(coach_ids)
        
        team.save()
        
        messages.success(request, 'Team has been updated!')
        return redirect('clients:team_detail', team_id=team.id)
    
    coaches = Coach.objects.filter(is_active=True)
    context = {
        'client': client,
        'team': team,
        'coaches': coaches,
        'skill_levels': Player.SKILL_LEVEL_CHOICES,
    }
    return render(request, 'clients/team_form.html', context)


@login_required
def team_player_add(request, team_id):
    """Add players to team roster."""
    client, created = Client.objects.get_or_create(user=request.user)
    team = get_object_or_404(Team, id=team_id, manager=client)
    
    if request.method == 'POST':
        player_id = request.POST.get('player_id')
        
        if player_id:
            player = get_object_or_404(Player, id=player_id, client=client)
            player.team = team
            player.save()
            messages.success(request, f'{player.first_name} has been added to the team!')
        else:
            # Create new player and add to team
            player = Player.objects.create(
                client=client,
                team=team,
                first_name=request.POST.get('first_name', ''),
                last_name=request.POST.get('last_name', ''),
                birth_year=int(request.POST.get('birth_year', timezone.now().year - 10)),
                gender=request.POST.get('gender', 'O'),
                skill_level=request.POST.get('skill_level', 'beginner'),
                primary_position=request.POST.get('primary_position', ''),
                notes=request.POST.get('notes', ''),
            )
            messages.success(request, f'{player.first_name} has been added to the team!')
        
        return redirect('clients:team_detail', team_id=team.id)
    
    # Get players not already on this team
    existing_player_ids = team.players.values_list('id', flat=True)
    available_players = client.players.filter(is_active=True).exclude(id__in=existing_player_ids)
    
    context = {
        'client': client,
        'team': team,
        'available_players': available_players,
        'genders': Player.GENDER_CHOICES,
        'skill_levels': Player.SKILL_LEVEL_CHOICES,
        'positions': Player.POSITION_CHOICES,
    }
    return render(request, 'clients/team_player_add.html', context)


@login_required
@require_POST
def team_player_remove(request, team_id, player_id):
    """Remove player from team roster."""
    client, created = Client.objects.get_or_create(user=request.user)
    team = get_object_or_404(Team, id=team_id, manager=client)
    player = get_object_or_404(Player, id=player_id, team=team, client=client)
    
    player.team = None
    player.save()
    
    messages.success(request, f'{player.first_name} has been removed from the team.')
    return redirect('clients:team_detail', team_id=team.id)


# ============================================================================
# TEAM BOOKING VIEWS
# ============================================================================

@login_required
def team_booking_page(request, team_id):
    """Team session booking page - book entire slots for team training."""
    client, created = Client.objects.get_or_create(user=request.user)
    team = get_object_or_404(Team, id=team_id, manager=client, is_active=True)
    
    # Check for active team package
    active_package = client.packages.filter(
        status='active',
        package__package_type='team',
        expiry_date__gte=timezone.now().date()
    ).first()
    
    if not active_package:
        messages.error(request, 'You need an active team package to book team sessions.')
        return redirect('clients:packages')
    
    # Get available schedule blocks for team training
    today = timezone.now().date()
    available_blocks = ScheduleBlock.objects.filter(
        date__gte=today,
        date__lte=today + timedelta(days=30),
        status='available',
        session_type='group'  # Team sessions use group slots
    ).select_related('coach').order_by('date', 'start_time')
    
    # Get team coaches' available slots first
    team_coach_blocks = available_blocks.filter(coach__in=team.coaches.all())
    other_blocks = available_blocks.exclude(coach__in=team.coaches.all())
    
    context = {
        'client': client,
        'team': team,
        'active_package': active_package,
        'sessions_remaining': active_package.sessions_remaining,
        'team_coach_blocks': team_coach_blocks,
        'other_blocks': other_blocks,
        'player_count': team.player_count,
        'available_field_rentals': FieldRentalSlot.objects.filter(
            date__gte=today, date__lte=today + timedelta(days=30), status='available'
        ).order_by('date', 'start_time'),
    }
    return render(request, 'clients/team_booking.html', context)


@login_required
@require_POST
def team_reserve_session(request, team_id):
    """Reserve a team training session slot."""
    client, created = Client.objects.get_or_create(user=request.user)
    team = get_object_or_404(Team, id=team_id, manager=client)
    
    block_id = request.POST.get('block_id')
    block = get_object_or_404(ScheduleBlock, id=block_id)

    # Check if field is exclusively reserved
    if FieldRentalSlot.check_field_blocked(block.date, block.start_time, block.end_time):
        return JsonResponse({'success': False,
            'error': 'The field is exclusively reserved during this time. No other bookings are possible.'})

    # Check if client has active team package
    active_package = client.packages.filter(
        status='active',
        package__package_type='team',
        expiry_date__gte=timezone.now().date()
    ).first()
    
    if not active_package:
        return JsonResponse({'success': False, 'error': 'No active team package'})
    
    # Check slot capacity for team size
    if block.spots_remaining < team.player_count:
        return JsonResponse({
            'success': False, 
            'error': f'Not enough spots. Slot has {block.spots_remaining} spots, team has {team.player_count} players.'
        })
    
    # Reserve the slot for the entire team (mark as fully booked)
    block.current_participants += team.player_count
    if block.current_participants >= block.max_participants:
        block.status = 'booked'
    block.save()
    
    # Create bookings for each player
    bookings_created = 0
    for player in team.active_players:
        Booking.objects.create(
            client=client,
            player=player,
            coach=block.coach,
            availability_slot=None,  # Using schedule block instead
            scheduled_date=block.date,
            scheduled_time=block.start_time,
            duration_minutes=block.duration_minutes,
            client_package=active_package,
            status='confirmed',
            payment_status='package',
            coach_notes=f'Team training session for {team.name}'
        )
        bookings_created += 1
    
    # Use one session from package per team booking
    active_package.use_session()
    
    return JsonResponse({
        'success': True,
        'bookings_created': bookings_created,
        'sessions_remaining': active_package.sessions_remaining
    })


@login_required
@require_POST
def team_confirm_booking(request, team_id):
    """Confirm team booking (placeholders for payment if needed)."""
    # Team bookings are auto-confirmed in team_reserve_session
    # This view handles any additional confirmation steps
    return JsonResponse({'success': True, 'message': 'Team booking confirmed!'})


@login_required
def team_bookings_list(request):
    """List all team bookings for the coach client."""
    client, created = Client.objects.get_or_create(user=request.user)
    
    if client.client_type != 'coach':
        messages.error(request, 'Team features are only available for team coaches.')
        return redirect('clients:dashboard')
    
    # Get all teams managed by this client
    teams = client.managed_teams.filter(is_active=True)
    team_ids = teams.values_list('id', flat=True)
    
    # Get bookings for players on these teams
    upcoming_bookings = Booking.objects.filter(
        player__team_id__in=team_ids,
        scheduled_date__gte=timezone.now().date(),
        status__in=['pending', 'confirmed']
    ).select_related('player', 'player__team', 'coach').order_by('scheduled_date', 'scheduled_time')
    
    past_bookings = Booking.objects.filter(
        player__team_id__in=team_ids,
        scheduled_date__lt=timezone.now().date()
    ).select_related('player', 'player__team', 'coach').order_by('-scheduled_date', '-scheduled_time')
    
    context = {
        'client': client,
        'teams': teams,
        'upcoming_bookings': upcoming_bookings,
        'past_bookings': past_bookings,
    }
    return render(request, 'clients/team_bookings.html', context)


# ============================================================================
# FIELD RENTAL VIEWS
# ============================================================================

@login_required
def field_rental_list(request):
    """Show available field rental slots and client's existing requests."""
    client, _ = Client.objects.get_or_create(user=request.user)
    today = timezone.now().date()
    preselect_team_id = request.GET.get('team')

    available_slots = FieldRentalSlot.objects.filter(
        date__gte=today,
        date__lte=today + timedelta(days=60),
        status='available'
    ).select_related('service').order_by('date', 'start_time')

    my_pending = FieldRentalSlot.objects.filter(
        booked_by_client=client,
        status='pending_approval'
    ).select_related('service').order_by('date')

    my_booked = FieldRentalSlot.objects.filter(
        booked_by_client=client,
        status='booked'
    ).select_related('service').order_by('date')

    # Also include slots booked by teams managed by this client
    my_teams = client.managed_teams.filter(is_active=True) if client.client_type == 'coach' else Team.objects.none()
    team_pending = FieldRentalSlot.objects.filter(booked_by_team__in=my_teams, status='pending_approval').select_related('service').order_by('date')
    team_booked = FieldRentalSlot.objects.filter(booked_by_team__in=my_teams, status='booked').select_related('service').order_by('date')

    context = {
        'client': client,
        'available_slots': available_slots,
        'my_pending': my_pending,
        'my_booked': my_booked,
        'team_pending': team_pending,
        'team_booked': team_booked,
        'my_teams': my_teams,
        'preselect_team_id': int(preselect_team_id) if preselect_team_id and preselect_team_id.isdigit() else None,
        'is_team_coach': client.client_type == 'coach',
    }
    return render(request, 'clients/field_rental.html', context)


@login_required
def field_rental_request(request, slot_id):
    """Submit a field rental request (sets slot to pending_approval)."""
    from django.db import transaction
    from django.contrib.auth.models import Group

    client, _ = Client.objects.get_or_create(user=request.user)

    if request.method == 'GET':
        slot = get_object_or_404(FieldRentalSlot, id=slot_id, status='available')
        my_teams = client.managed_teams.filter(is_active=True) if client.client_type == 'coach' else Team.objects.none()
        preselect_team_id = request.GET.get('team')
        return render(request, 'clients/field_rental_request.html', {
            'slot': slot,
            'client': client,
            'my_teams': my_teams,
            'preselect_team_id': int(preselect_team_id) if preselect_team_id and preselect_team_id.isdigit() else None,
        })

    # POST
    with transaction.atomic():
        slot = get_object_or_404(FieldRentalSlot.objects.select_for_update(), id=slot_id)
        if slot.status != 'available':
            messages.error(request, 'This slot is no longer available.')
            return redirect('clients:field_rental_list')

        # Same-service conflict: block if another slot for this service already
        # occupies an overlapping window (pending or confirmed).
        service_conflicts = slot.get_same_service_conflicts()
        if service_conflicts.exists():
            conflict = service_conflicts.first()
            messages.error(
                request,
                f'Sorry — "{slot.service.name}" is already reserved for '
                f'{conflict.start_time:%I:%M %p}–{conflict.end_time:%I:%M %p} '
                f'on {conflict.date:%b %d}. Please choose a different time.'
            )
            return redirect('clients:field_rental_list')

        booker_type = request.POST.get('booker_type', 'individual')
        team = None
        if booker_type == 'team':
            team_id = request.POST.get('team_id')
            team = get_object_or_404(Team, id=team_id, manager=client, is_active=True)

        slot.status = 'pending_approval'
        slot.booked_by_client = client
        slot.booked_by_team = team
        slot.booker_type = booker_type
        slot.client_notes = request.POST.get('client_notes', '')
        slot.requested_at = timezone.now()
        slot.save()

    # Notify owner(s)
    requester_name = (team.name if team else client.user.get_full_name()) or client.user.username
    owner_clients = Client.objects.filter(user__groups__name='Owner')
    for oc in owner_clients:
        Notification.objects.create(
            client=oc,
            notification_type='field_rental_request',
            title='New Field Rental Request',
            message=f'{requester_name} has requested the field on {slot.date:%b %d, %Y} '
                    f'from {slot.start_time:%I:%M %p} to {slot.end_time:%I:%M %p}.',
            method='email',
        )

    messages.success(request, 'Your field rental request has been submitted! The owner will review and confirm.')
    return redirect('clients:field_rental_list')


@login_required
@require_POST
def field_rental_cancel(request, slot_id):
    """Cancel a pending field rental request (before owner approval)."""
    client, _ = Client.objects.get_or_create(user=request.user)
    slot = get_object_or_404(FieldRentalSlot, id=slot_id, booked_by_client=client, status='pending_approval')

    slot.status = 'available'
    slot.booked_by_client = None
    slot.booked_by_team = None
    slot.booker_type = None
    slot.client_notes = ''
    slot.requested_at = None
    slot.cancelled_at = timezone.now()
    slot.save()

    messages.success(request, 'Your field rental request has been cancelled.')
    return redirect('clients:field_rental_list')


@login_required
def field_rental_available_json(request):
    """JSON API: available field rental slots for calendar overlay."""
    today = timezone.now().date()
    slots = FieldRentalSlot.objects.filter(
        date__gte=today,
        date__lte=today + timedelta(days=60),
        status='available'
    ).values('id', 'date', 'start_time', 'end_time', 'price', 'title', 'duration_minutes')
    return JsonResponse({'slots': list(slots)}, json_dumps_params={'default': str})
