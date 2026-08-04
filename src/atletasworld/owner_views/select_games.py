from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from clients.models import Client
from coaches.models import Coach
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_select_games(request):
    """List and create APC Select games."""
    from bookings.models import SelectGame, SelectGameRSVP
    from clients.models import Team

    select_teams = Team.objects.filter(is_select=True, is_active=True).order_by('name')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            team_id = request.POST.get('team_id')
            date = request.POST.get('date')
            start_time = request.POST.get('start_time')
            end_time = request.POST.get('end_time') or None
            location = request.POST.get('location', '').strip()
            notes = request.POST.get('notes', '').strip()
            coach_id = request.POST.get('coach_id') or None
            publish = request.POST.get('publish') == '1'

            try:
                from datetime import date as date_cls, time as time_cls
                date = date_cls.fromisoformat(date)
                start_time = time_cls.fromisoformat(start_time)
                end_time = time_cls.fromisoformat(end_time) if end_time else None
                team = Team.objects.get(pk=team_id, is_select=True)
                game = SelectGame.objects.create(
                    team=team,
                    created_by=request.user,
                    coach_id=coach_id,
                    date=date,
                    start_time=start_time,
                    end_time=end_time,
                    location=location,
                    notes=notes,
                    status='published' if publish else 'draft',
                )
                # Add manually specified guest invitees
                guest_ids = request.POST.getlist('guest_client_ids')
                if guest_ids:
                    game.guest_invitees.set(Client.objects.filter(pk__in=guest_ids))
                    game.save()
                messages.success(request, f'Game created{"and published" if publish else " as draft"}.')
                return redirect('owner_select_game_detail', game_id=game.pk)
            except Exception as e:
                messages.error(request, f'Error creating game: {e}')

    today = timezone.localdate()
    upcoming = SelectGame.objects.filter(
        date__gte=today
    ).select_related('team', 'coach__user').order_by('date', 'start_time')
    past = SelectGame.objects.filter(
        date__lt=today
    ).select_related('team', 'coach__user').order_by('-date')[:20]

    # Annotate RSVP counts
    from django.db.models import Count as _Count
    upcoming = upcoming.annotate(
        coming_count=_Count('rsvps', filter=Q(rsvps__status='coming')),
        pending_count=_Count('rsvps', filter=Q(rsvps__status='pending')),
    )

    coaches = Coach.objects.filter(is_active=True).select_related('user').order_by('user__first_name')
    all_clients = Client.objects.select_related('user').order_by('user__first_name')

    return render(request, 'owner/select_games.html', {
        'upcoming_games': upcoming,
        'past_games': past,
        'select_teams': select_teams,
        'coaches': coaches,
        'all_clients': all_clients,
    })


@login_required
@user_passes_test(is_owner)
def owner_select_game_detail(request, game_id):
    """View and manage a single Select game — roster, RSVP status, publish/cancel."""
    from bookings.models import SelectGame, SelectGameRSVP
    from clients.models import Team

    game = get_object_or_404(SelectGame, pk=game_id)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'publish' and game.status == 'draft':
            game.status = 'published'
            game.save()
            messages.success(request, 'Game published — invites sent to all eligible Select members.')
        elif action == 'cancel':
            game.status = 'cancelled'
            game.save()
            messages.success(request, 'Game cancelled.')
        elif action == 'add_guest':
            client_id = request.POST.get('client_id')
            if client_id:
                try:
                    guest = Client.objects.get(pk=client_id)
                    game.guest_invitees.add(guest)
                    if game.status == 'published':
                        # Create RSVP for newly added guest
                        SelectGameRSVP.objects.get_or_create(
                            game=game, client=guest, defaults={'status': 'pending'}
                        )
                    messages.success(request, f'{guest} added as guest.')
                except Client.DoesNotExist:
                    messages.error(request, 'Client not found.')
        return redirect('owner_select_game_detail', game_id=game_id)

    rsvps = game.rsvps.select_related('client__user', 'player').order_by('client__user__first_name')
    coming = [r for r in rsvps if r.status == 'coming']
    not_coming = [r for r in rsvps if r.status == 'not_coming']
    pending = [r for r in rsvps if r.status == 'pending']
    all_clients = Client.objects.select_related('user').order_by('user__first_name')

    return render(request, 'owner/select_game_detail.html', {
        'game': game,
        'rsvps': rsvps,
        'coming': coming,
        'not_coming': not_coming,
        'pending': pending,
        'all_clients': all_clients,
    })
