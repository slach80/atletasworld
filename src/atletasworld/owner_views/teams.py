from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from clients.models import Client, Player, ClientPackage
from bookings.models import Booking
from coaches.models import Coach
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_teams(request):
    """List all teams with stats; handle team creation via POST."""
    from clients.models import Team, ClientPackage
    from django.db.models import Count, Q
    from django.utils.text import slugify

    if request.method == 'POST' and request.POST.get('action') == 'create':
        name = request.POST.get('name', '').strip()
        age_group = request.POST.get('age_group', '').strip()
        skill_level = request.POST.get('skill_level', 'intermediate')
        max_players = request.POST.get('max_players', 18)
        description = request.POST.get('description', '').strip()
        is_select = request.POST.get('is_select') == '1'

        if name and age_group:
            base_slug = slugify(name)
            slug = base_slug
            counter = 1
            while Team.objects.filter(slug=slug).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            try:
                max_players = int(max_players)
            except (ValueError, TypeError):
                max_players = 18
            manager_client = Client.objects.filter(user__groups__name='Owner').first()
            Team.objects.create(
                name=name,
                slug=slug,
                age_group=age_group,
                skill_level=skill_level,
                max_players=max_players,
                description=description,
                is_select=is_select,
                is_active=True,
                manager=manager_client,
            )
            messages.success(request, f'Team "{name}" created.')
        else:
            messages.error(request, 'Name and age group are required.')
        return redirect('owner_teams')

    teams = Team.objects.filter(is_active=True).annotate(
        active_player_count=Count('players', filter=Q(players__is_active=True)),
        coach_count=Count('coaches')
    ).order_by('age_group', 'name')

    # Calculate stats
    total_teams = teams.count()
    total_players = Player.objects.filter(is_active=True, team__is_active=True).count()
    total_coaches = Coach.objects.filter(teams__is_active=True).distinct().count()

    # Count active team packages
    active_packages = ClientPackage.objects.filter(
        status='active',
        package__package_type='team'
    ).count()

    context = {
        'teams': teams,
        'total_teams': total_teams,
        'total_players': total_players,
        'total_coaches': total_coaches,
        'active_packages': active_packages,
    }
    return render(request, 'owner/teams.html', context)


@login_required
@user_passes_test(is_owner)
def owner_team_detail(request, pk):
    """Show detailed team info; handle team edit, deactivate, and roster management via POST."""
    from clients.models import Team
    from django.shortcuts import get_object_or_404
    from datetime import timedelta

    team = get_object_or_404(Team.objects.select_related('manager__user'), pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'edit':
            team.name = request.POST.get('name', team.name).strip() or team.name
            team.age_group = request.POST.get('age_group', team.age_group).strip() or team.age_group
            team.skill_level = request.POST.get('skill_level', team.skill_level)
            team.description = request.POST.get('description', '').strip()
            team.is_select = request.POST.get('is_select') == '1'
            try:
                team.max_players = int(request.POST.get('max_players', team.max_players))
            except (ValueError, TypeError):
                pass
            team.save()
            messages.success(request, f'Team "{team.name}" updated.')
        elif action == 'deactivate':
            team.is_active = False
            team.save()
            messages.success(request, f'Team "{team.name}" deactivated.')
            return redirect('owner_teams')
        elif action == 'assign_primary':
            player_id = request.POST.get('player_id')
            if player_id:
                player = get_object_or_404(Player, pk=player_id, is_active=True)
                player.team = team
                player.save()
                messages.success(request, f'{player.first_name} {player.last_name} assigned to {team.name}.')
        elif action == 'remove_primary':
            player_id = request.POST.get('player_id')
            if player_id:
                player = get_object_or_404(Player, pk=player_id, team=team)
                player.team = None
                player.save()
                messages.success(request, f'{player.first_name} {player.last_name} removed from {team.name}.')
        elif action == 'add_guest':
            player_id = request.POST.get('player_id')
            if player_id:
                player = get_object_or_404(Player, pk=player_id, is_active=True)
                player.select_teams.add(team)
                messages.success(request, f'{player.first_name} {player.last_name} added as guest callup.')
        elif action == 'remove_guest':
            player_id = request.POST.get('player_id')
            if player_id:
                player = get_object_or_404(Player, pk=player_id, is_active=True)
                player.select_teams.remove(team)
                messages.success(request, f'{player.first_name} {player.last_name} removed from guest callups.')
        return redirect('owner_team_detail', pk=pk)

    today = timezone.localdate()

    # Primary roster (FK) and guest callups (M2M)
    primary_players = Player.objects.filter(team=team, is_active=True).select_related('client__user').order_by('first_name', 'last_name')
    guest_players = team.select_guest_players.filter(is_active=True).select_related('client__user').order_by('first_name', 'last_name')

    # Players not on this team in any capacity — for the add modals
    primary_ids = set(primary_players.values_list('id', flat=True))
    guest_ids = set(guest_players.values_list('id', flat=True))
    already_on_team = primary_ids | guest_ids
    available_players = Player.objects.filter(is_active=True).exclude(id__in=already_on_team).select_related('client__user').order_by('first_name', 'last_name')

    # Get assigned coaches
    coaches = team.coaches.all().select_related('user')

    # Upcoming Select practice/game sessions — both primary and guest players
    SELECT_SESSION_TYPE_IDS = [21, 22, 23, 25]
    all_team_player_ids = already_on_team
    upcoming_bookings = Booking.objects.filter(
        player_id__in=all_team_player_ids,
        scheduled_date__gte=today,
        status__in=['pending', 'confirmed'],
        session_type_id__in=SELECT_SESSION_TYPE_IDS,
    ).select_related('player', 'coach__user', 'session_type').order_by('scheduled_date')[:20]

    # Select membership packages for all team players (primary + guest)
    from clients.models import ClientPackage
    from django.db.models import Case, When, Value, IntegerField
    _raw_team_packages = ClientPackage.objects.filter(
        player_id__in=all_team_player_ids,
        package__package_type='select',
    ).select_related('package', 'player').annotate(
        status_rank=Case(
            When(status='active', then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by('player_id', 'status_rank', '-expiry_date')

    # Keep only the most-recent package per player, then compute display status
    _seen_players = set()
    team_packages = []
    for cp in _raw_team_packages:
        pid = cp.player_id
        if pid in _seen_players:
            continue
        _seen_players.add(pid)
        days_left = (cp.expiry_date - today).days if cp.expiry_date else -1
        if days_left < 0:
            cp.display_status = 'expired'
        elif cp.status == 'active' and days_left <= 14:
            cp.display_status = 'expiring'
        elif cp.status == 'active':
            cp.display_status = 'active'
        else:
            cp.display_status = 'paid'
        team_packages.append(cp)

    context = {
        'team': team,
        'players': primary_players,
        'guest_players': guest_players,
        'available_players': available_players,
        'coaches': coaches,
        'upcoming_bookings': upcoming_bookings,
        'team_packages': team_packages,
        'player_count': primary_players.count(),
        'guest_count': guest_players.count(),
        'coach_count': coaches.count(),
    }
    return render(request, 'owner/team_detail.html', context)


@login_required
@user_passes_test(is_owner)
def owner_team_players(request, team_id):
    """View all players on a specific team."""
    from clients.models import Team
    from django.shortcuts import get_object_or_404

    team = get_object_or_404(Team.objects.select_related('manager__user'), pk=team_id)

    players = Player.objects.filter(team=team, is_active=True).select_related('client__user').annotate(
        total_bookings=Count('bookings'),
        total_assessments=Count('assessments')
    ).order_by('first_name', 'last_name')

    context = {
        'team': team,
        'players': players,
    }
    return render(request, 'owner/team_players.html', context)


@login_required
@user_passes_test(is_owner)
def owner_team_bookings(request, team_id):
    """View all bookings for a specific team."""
    from clients.models import Team
    from django.shortcuts import get_object_or_404

    team = get_object_or_404(Team.objects.select_related('manager__user'), pk=team_id)
    today = timezone.localdate()

    # Get date filters from request
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    bookings = Booking.objects.filter(player__team=team).select_related(
        'player', 'coach__user', 'session_type'
    ).order_by('-scheduled_date', '-scheduled_time')

    if date_from:
        bookings = bookings.filter(scheduled_date__gte=date_from)
    if date_to:
        bookings = bookings.filter(scheduled_date__lte=date_to)

    # Calculate summary stats — single aggregate instead of 4 count queries
    booking_stats = bookings.aggregate(
        total_bookings=Count('id'),
        completed_bookings=Count('id', filter=Q(status='completed')),
        upcoming_bookings=Count('id', filter=Q(scheduled_date__gte=today, status__in=['pending', 'confirmed'])),
        cancelled_bookings=Count('id', filter=Q(status='cancelled')),
    )
    total_bookings     = booking_stats['total_bookings'] or 0
    completed_bookings = booking_stats['completed_bookings'] or 0
    upcoming_bookings  = booking_stats['upcoming_bookings'] or 0
    cancelled_bookings = booking_stats['cancelled_bookings'] or 0

    context = {
        'team': team,
        'bookings': bookings[:100],
        'total_bookings': total_bookings,
        'completed_bookings': completed_bookings,
        'upcoming_bookings': upcoming_bookings,
        'cancelled_bookings': cancelled_bookings,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'owner/team_bookings.html', context)
