from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone

from clients.models import Client, Player, Team, FieldRentalSlot
from bookings.models import Booking
from coaches.models import Coach, ScheduleBlock


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
        scheduled_date__gte=timezone.localdate(),
        status__in=['pending', 'confirmed']
    ).select_related('player', 'coach').order_by('scheduled_date', 'scheduled_time')

    # Check for active team package
    active_package = client.packages.filter(
        status='active',
        package__package_type='team',
        expiry_date__gte=timezone.localdate()
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
        expiry_date__gte=timezone.localdate()
    ).first()

    if not active_package:
        messages.error(request, 'You need an active team package to book team sessions.')
        return redirect('clients:packages')

    # Get available schedule blocks for team training
    today = timezone.localdate()
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
        expiry_date__gte=timezone.localdate()
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
        scheduled_date__gte=timezone.localdate(),
        status__in=['pending', 'confirmed']
    ).select_related('player', 'player__team', 'coach').order_by('scheduled_date', 'scheduled_time')

    past_bookings = Booking.objects.filter(
        player__team_id__in=team_ids,
        scheduled_date__lt=timezone.localdate()
    ).select_related('player', 'player__team', 'coach').order_by('-scheduled_date', '-scheduled_time')

    context = {
        'client': client,
        'teams': teams,
        'upcoming_bookings': upcoming_bookings,
        'past_bookings': past_bookings,
    }
    return render(request, 'clients/team_bookings.html', context)
