from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from coaches.models import Coach
from ._auth import coach_required


@coach_required
def coach_select_games(request):
    """Coach view: list, create, and manage Select games."""
    from bookings.models import SelectGame, SelectGameRSVP
    from clients.models import Team, Client

    coach = get_object_or_404(Coach, user=request.user)
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
                    coach=coach,
                    date=date,
                    start_time=start_time,
                    end_time=end_time,
                    location=location,
                    notes=notes,
                    status='published' if publish else 'draft',
                )
                guest_ids = request.POST.getlist('guest_client_ids')
                if guest_ids:
                    game.guest_invitees.set(Client.objects.filter(pk__in=guest_ids))
                    game.save()
                messages.success(request, f'Game {"published" if publish else "saved as draft"}.')
                return redirect('coaches:select_game_detail', game_id=game.pk)
            except Exception as e:
                messages.error(request, f'Error creating game: {e}')

    today = timezone.localdate()
    from django.db.models import Count as _Count
    upcoming = SelectGame.objects.filter(
        Q(coach=coach) | Q(created_by=request.user),
        date__gte=today,
    ).select_related('team').annotate(
        coming_count=_Count('rsvps', filter=Q(rsvps__status='coming')),
        pending_count=_Count('rsvps', filter=Q(rsvps__status='pending')),
    ).order_by('date', 'start_time')
    past = SelectGame.objects.filter(
        Q(coach=coach) | Q(created_by=request.user),
        date__lt=today,
    ).select_related('team').order_by('-date')[:20]

    all_clients = Client.objects.select_related('user').order_by('user__first_name')

    return render(request, 'coaches/select_games.html', {
        'coach': coach,
        'upcoming_games': upcoming,
        'past_games': past,
        'select_teams': select_teams,
        'all_clients': all_clients,
    })


@coach_required
def coach_select_game_detail(request, game_id):
    """Coach view: single Select game roster and RSVP board."""
    from bookings.models import SelectGame, SelectGameRSVP, Booking
    from clients.models import Client

    coach = get_object_or_404(Coach, user=request.user)
    game = get_object_or_404(SelectGame, pk=game_id, coach=coach)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'publish' and game.status == 'draft':
            game.status = 'published'
            game.save()
            messages.success(request, 'Game published — Select members notified.')
        elif action == 'add_guest':
            client_id = request.POST.get('client_id')
            if client_id:
                try:
                    guest = Client.objects.get(pk=client_id)
                    game.guest_invitees.add(guest)
                    if game.status == 'published':
                        SelectGameRSVP.objects.get_or_create(
                            game=game, client=guest, defaults={'status': 'pending'}
                        )
                    messages.success(request, f'{guest} added as guest.')
                except Client.DoesNotExist:
                    messages.error(request, 'Client not found.')
        return redirect('coaches:select_game_detail', game_id=game_id)

    rsvps = game.rsvps.select_related('client__user', 'player').order_by('client__user__first_name')
    # Limit guest candidates to clients this coach has worked with, not the entire roster.
    coached_client_ids = Booking.objects.filter(coach=coach).values_list('client_id', flat=True).distinct()
    all_clients = Client.objects.filter(pk__in=coached_client_ids).select_related('user').order_by('user__first_name')

    return render(request, 'coaches/select_game_detail.html', {
        'coach': coach,
        'game': game,
        'coming': [r for r in rsvps if r.status == 'coming'],
        'not_coming': [r for r in rsvps if r.status == 'not_coming'],
        'pending': [r for r in rsvps if r.status == 'pending'],
        'all_clients': all_clients,
    })
