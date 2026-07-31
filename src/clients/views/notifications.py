from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone

from clients.models import Client, NotificationPreference, Notification, PushSubscription


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

        # Master email opt-out (checkbox present == unsubscribe from everything).
        from clients.models import EmailSuppression
        opt_out = request.POST.get('email_opt_out') == 'on'
        prefs.email_opt_out = opt_out
        prefs.email_opt_out_at = timezone.now() if opt_out else None
        if opt_out:
            EmailSuppression.suppress(request.user.email, reason='portal preferences')
        else:
            EmailSuppression.resubscribe(request.user.email)
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
