from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from coaches.models import Coach
from bookings.models import Booking
from clients.models import Notification
from ._auth import coach_required


@coach_required
def notify_parents(request):
    """Page to send notifications to parents."""
    coach = request.coach
    from clients.models import Player, Client

    # Get all unique clients from players coached
    player_ids = Booking.objects.filter(
        coach=coach
    ).values_list('player_id', flat=True).distinct()

    clients = Client.objects.filter(
        players__id__in=player_ids
    ).distinct().prefetch_related('players')

    context = {
        'coach': coach,
        'clients': clients,
    }
    return render(request, 'coaches/notify_parents.html', context)


@coach_required
@require_POST
def send_notification(request):
    """Send notifications to multiple players' parents."""
    coach = request.coach
    from clients.models import Player

    player_ids = request.POST.getlist('player_ids')
    notification_type = request.POST.get('notification_type', 'general')
    message = request.POST.get('message', '')

    if player_ids and message:
        # Get unique clients from selected players
        players = Player.objects.filter(id__in=player_ids).select_related('client')
        notified_clients = set()
        sent_count = 0

        for player in players:
            client = player.client
            # Avoid sending duplicate notifications to the same client
            if client.id in notified_clients:
                continue
            notified_clients.add(client.id)

            # Get notification preference
            try:
                prefs = client.notification_preferences
                method = prefs.booking_confirmations
            except Exception:
                method = 'email'

            # Create and send notification
            notification = Notification.objects.create(
                client=client,
                notification_type=notification_type,
                title=f'Message from Coach {coach.user.first_name or coach.user.username}',
                message=message,
                method=method,
            )
            notification.send()
            sent_count += 1

        failed = [n for n in Notification.objects.filter(
            client__players__id__in=player_ids,
            status='failed'
        ).values_list('client__user__email', flat=True)]

        if sent_count == 1:
            messages.success(request, f'Notification sent to 1 parent.')
        else:
            messages.success(request, f'Notifications sent to {sent_count} parents.')
        if failed:
            messages.warning(request, f'Failed to deliver to: {", ".join(set(failed))}')
    else:
        messages.error(request, 'Please select recipients and provide a message.')

    return redirect('coaches:notify_parents')


@coach_required
def notify_ai_assist(request):
    """AI Assist endpoint for the notify-parents message composer."""
    import requests as _requests
    from django.conf import settings as _settings

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    action = request.POST.get('action', '')
    message = request.POST.get('message', '').strip()
    notification_type = request.POST.get('notification_type', 'general')

    TYPE_LABELS = {
        'schedule_change': 'schedule change',
        'session_reminder': 'session reminder',
        'assessment_ready': 'assessment ready notification',
        'general': 'general parent message',
    }
    type_label = TYPE_LABELS.get(notification_type, 'general message')

    PROMPTS = {
        'draft': (
            f"You are a youth soccer coach at Atletas Performance Center (APC), an elite academy "
            f"in Overland Park, Kansas City. Write a short, warm, professional parent notification "
            f"email for a '{type_label}'.\n\n"
            f"Requirements:\n"
            f"- Plain text only, no HTML\n"
            f"- 3-5 sentences max\n"
            f"- Friendly but professional tone\n"
            f"- Leave [brackets] for details the coach should fill in\n"
            f"- Sign off as 'APC Coaching Staff'\n"
            f"Return ONLY the message text."
        ),
        'grammar': (
            f"Fix the spelling, grammar, and tone of the following parent notification message. "
            f"Keep the meaning and length the same. Plain text only.\n\n"
            f"Message:\n{message}\n\n"
            f"Return ONLY the corrected message."
        ),
        'shorten': (
            f"Shorten the following parent notification message to 2-3 sentences maximum. "
            f"Keep the key information. Plain text only.\n\n"
            f"Message:\n{message}\n\n"
            f"Return ONLY the shortened message."
        ),
    }

    prompt = PROMPTS.get(action)
    if not prompt:
        return JsonResponse({'error': 'Invalid action'}, status=400)

    if action != 'draft' and not message:
        return JsonResponse({'error': 'Message is empty — nothing to improve.'}, status=400)

    ollama_url = getattr(_settings, 'OLLAMA_BASE_URL', 'http://192.168.1.70:11434')
    model = getattr(_settings, 'OLLAMA_MODEL', 'qwen3:8b-32k')

    try:
        resp = _requests.post(
            f'{ollama_url}/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False, 'options': {'temperature': 0.6}},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json().get('response', '').strip()
        return JsonResponse({'result': result})
    except _requests.exceptions.Timeout:
        return JsonResponse({'error': 'AI request timed out. Try again.'}, status=504)
    except Exception as e:
        return JsonResponse({'error': f'AI unavailable: {str(e)}'}, status=503)
