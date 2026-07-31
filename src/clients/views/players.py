from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone

from clients.models import Client, Player
from clients.utils import validate_photo as _validate_photo, _MAX_PHOTO_BYTES, _ALLOWED_PHOTO_EXTENSIONS


@login_required
def players_list(request):
    """List all players for the client."""
    client, created = Client.objects.get_or_create(user=request.user)
    players = client.players.filter(is_active=True)

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
            jersey_size=request.POST.get('jersey_size', ''),
            favorite_national_team=request.POST.get('favorite_national_team', ''),
            favorite_club_team=request.POST.get('favorite_club_team', ''),
        )
        if request.FILES.get('photo'):
            err = _validate_photo(request.FILES['photo'])
            if err:
                messages.error(request, err)
                return redirect(request.path)
            player.photo = request.FILES['photo']
            player.save()
        messages.success(request, f'{player.first_name} has been added!')
        next_url = request.POST.get('next') or request.GET.get('next', '')
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        return redirect('clients:players')

    context = {
        'skill_levels': Player.SKILL_LEVEL_CHOICES,
        'positions': Player.POSITION_CHOICES,
        'genders': Player.GENDER_CHOICES,
        'grades': Player.GRADE_CHOICES,
        'jersey_sizes': Player.JERSEY_SIZE_CHOICES,
        'next': request.GET.get('next', ''),
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
        player.jersey_size = request.POST.get('jersey_size', '')
        player.favorite_national_team = request.POST.get('favorite_national_team', '')
        player.favorite_club_team = request.POST.get('favorite_club_team', '')
        if request.FILES.get('photo'):
            err = _validate_photo(request.FILES['photo'])
            if err:
                messages.error(request, err)
                return redirect(request.path)
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
        'jersey_sizes': Player.JERSEY_SIZE_CHOICES,
    }
    return render(request, 'clients/player_form.html', context)


@login_required
@require_POST
def player_delete(request, player_id):
    """Delete (deactivate) a player."""
    client, created = Client.objects.get_or_create(user=request.user)
    player = get_object_or_404(Player, id=player_id, client=client)

    # Check for active packages
    from bookings.models import ClientPackage, Booking
    active_packages = ClientPackage.objects.filter(player=player, status='active')
    active_bookings = Booking.objects.filter(player=player, status__in=['confirmed', 'pending'])

    if active_packages.exists() or active_bookings.exists():
        warning_parts = []
        if active_packages.exists():
            warning_parts.append(f"{active_packages.count()} active package(s)")
        if active_bookings.exists():
            warning_parts.append(f"{active_bookings.count()} active booking(s)")

        messages.warning(
            request,
            f'⚠️ {player.first_name} has {" and ".join(warning_parts)}. '
            f'Removing this player may affect their access to sessions and packages.'
        )

    player.is_active = False
    player.save()

    messages.success(request, f'{player.first_name} has been removed.')
    return redirect('clients:players')
