from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from django.views.decorators.http import require_POST
from clients.models import Client, Player, ClientPackage
from bookings.models import Booking
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_clients(request):
    """List all clients with their players - only users in Client group."""
    from clients.models import ClientPackage
    from django.contrib.auth.models import Group
    from django.core.paginator import Paginator

    search = request.GET.get('q', '').strip()
    has_package = request.GET.get('has_package', '')

    client_group = Group.objects.filter(name='Client').first()
    if client_group:
        client_user_ids = client_group.user_set.values_list('id', flat=True)
        qs = Client.objects.filter(user_id__in=client_user_ids).select_related('user').annotate(
            player_count=Count('players', distinct=True),
            active_packages=Count('packages', filter=Q(packages__status='active'), distinct=True),
            total_bookings=Count('bookings', distinct=True)
        ).order_by('-created_at')
    else:
        qs = Client.objects.none()

    if search:
        qs = qs.filter(
            Q(user__first_name__icontains=search) |
            Q(user__last_name__icontains=search) |
            Q(user__email__icontains=search) |
            Q(phone__icontains=search) |
            Q(players__first_name__icontains=search) |
            Q(players__last_name__icontains=search)
        ).distinct()

    if has_package == '1':
        qs = qs.filter(active_packages__gt=0)
    elif has_package == '0':
        qs = qs.filter(active_packages=0)

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page', 1))

    context = {
        'clients': page,
        'paginator': paginator,
        'page_obj': page,
        'search': search,
        'has_package': has_package,
    }
    return render(request, 'owner/clients.html', context)


@login_required
@user_passes_test(is_owner)
def owner_client_detail(request, pk):
    """View a client's details including players and bookings."""
    from django.shortcuts import get_object_or_404
    from clients.models import ClientPackage, RentalService

    client = get_object_or_404(Client.objects.select_related('user').prefetch_related('allowed_services'), pk=pk)
    players = Player.objects.filter(client=client, is_active=True)
    packages = ClientPackage.objects.filter(client=client).select_related('package')
    recent_bookings = Booking.objects.filter(client=client).select_related('player', 'coach__user')[:20]
    all_services = RentalService.objects.filter(is_active=True)
    pending_payment_count = Booking.objects.filter(
        client=client, status__in=['pending', 'confirmed']
    ).filter(
        Q(payment_status='pending') |
        Q(session_type__requires_package=True, client_package__isnull=True)
    ).count()
    eligible_packages = [p for p in packages if p.is_valid and p.sessions_remaining > 0]

    context = {
        'client': client,
        'players': players,
        'packages': packages,
        'recent_bookings': recent_bookings,
        'all_services': all_services,
        'allowed_service_ids': list(client.allowed_services.values_list('id', flat=True)),
        'pending_payment_count': pending_payment_count,
        'eligible_packages': eligible_packages,
    }
    return render(request, 'owner/client_detail.html', context)


@login_required
@user_passes_test(is_owner)
def owner_client_settle_bookings(request, pk):
    """Bulk-settle all pending-payment bookings for a client via a chosen package."""
    import json
    from django.http import JsonResponse
    from clients.models import ClientPackage

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    client = get_object_or_404(Client, pk=pk)
    try:
        data = json.loads(request.body)
        package_id = int(data['package_id'])
        package = ClientPackage.objects.get(pk=package_id, client=client)
    except (KeyError, ValueError, ClientPackage.DoesNotExist):
        return JsonResponse({'error': 'Invalid package'}, status=400)

    if not package.is_valid:
        return JsonResponse({'error': 'Package is expired or inactive'}, status=400)

    # Match exactly what the client portal shows as "Payment Required":
    # (1) payment_status='pending' OR
    # (2) requires_package=True with no package linked
    unsettled_bookings = Booking.objects.filter(
        client=client, status__in=['pending', 'confirmed']
    ).filter(
        Q(payment_status='pending') |
        Q(session_type__requires_package=True, client_package__isnull=True)
    ).order_by('scheduled_date', 'scheduled_time')

    settled = 0
    skipped = 0
    for booking in unsettled_bookings:
        if package.sessions_remaining <= 0:
            skipped += 1
            continue
        try:
            booking.client_package = package
            booking.payment_status = 'package'
            booking.save()
            package.sessions_remaining -= 1
            package.sessions_used += 1
            settled += 1
        except Exception:
            skipped += 1

    if package.sessions_remaining == 0:
        package.status = 'exhausted'
    package.save()

    return JsonResponse({
        'settled': settled,
        'skipped': skipped,
        'sessions_remaining': package.sessions_remaining,
    })


@login_required
@user_passes_test(is_owner)
def owner_client_approve(request, pk):
    """Approve a coach or renter client with term dates and allowed services."""
    from django.shortcuts import get_object_or_404
    from django.utils import timezone
    from clients.models import RentalService, Notification

    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        term_start_str = request.POST.get('term_start', '').strip()
        term_end_str   = request.POST.get('term_end', '').strip()
        service_ids    = request.POST.getlist('allowed_services')
        notes          = request.POST.get('approval_notes', '').strip()

        from datetime import datetime
        def parse_dt(s):
            for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue
            return None

        client.approval_status = 'approved'
        client.approved_by     = request.user
        client.approved_at     = timezone.now()
        client.approval_notes  = notes
        client.term_start      = parse_dt(term_start_str) if term_start_str else None
        client.term_end        = parse_dt(term_end_str) if term_end_str else None
        client.save()
        client.allowed_services.set(RentalService.objects.filter(id__in=service_ids))

        # Notify client
        Notification.objects.create(
            client=client,
            notification_type='promotional',
            title='Your access has been approved!',
            message=f'Your {client.get_client_type_display()} access has been approved by APC.'
                    + (f'\nTerm: {client.term_start.strftime("%b %d, %Y") if client.term_start else "Immediate"}'
                       + (f' → {client.term_end.strftime("%b %d, %Y")}' if client.term_end else '') if client.term_start or client.term_end else ''),
            method='email',
        ).send()

        messages.success(request, f'{client} approved successfully.')
    return redirect('owner_client_detail', pk=pk)


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_client_toggle_select_invite(request, pk):
    """Toggle APC Select invite status for a client."""
    from django.shortcuts import get_object_or_404
    client = get_object_or_404(Client, pk=pk)
    client.select_invited = not client.select_invited
    client.save(update_fields=['select_invited'])
    status = 'invited' if client.select_invited else 'invite revoked'
    messages.success(request, f'{client} APC Select {status}.')
    return redirect('owner_client_detail', pk=pk)


@login_required
@user_passes_test(is_owner)
def owner_client_reject(request, pk):
    """Reject a coach or renter client access request."""
    from django.shortcuts import get_object_or_404
    from django.utils import timezone
    from clients.models import Notification

    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        notes = request.POST.get('rejection_notes', '').strip()
        client.approval_status = 'rejected'
        client.rejected_at     = timezone.now()
        client.approval_notes  = notes
        client.save()

        Notification.objects.create(
            client=client,
            notification_type='promotional',
            title='Access request not approved',
            message=f'Your {client.get_client_type_display()} access request could not be approved at this time.'
                    + (f'\n\nNote from APC: {notes}' if notes else '')
                    + '\n\nPlease contact us if you have questions.',
            method='email',
        ).send()

        messages.warning(request, f'{client} access rejected.')
    return redirect('owner_client_detail', pk=pk)
