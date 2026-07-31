from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone

from clients.models import Client, Team, FieldRentalSlot, Notification


# ============================================================================
# FIELD RENTAL VIEWS
# ============================================================================

@login_required
def field_rental_list(request):
    """Show available field rental slots and client's existing requests."""
    client, _ = Client.objects.get_or_create(user=request.user)
    today = timezone.localdate()
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
    today = timezone.localdate()
    slots = FieldRentalSlot.objects.filter(
        date__gte=today,
        date__lte=today + timedelta(days=60),
        status='available'
    ).values('id', 'date', 'start_time', 'end_time', 'price', 'title', 'duration_minutes')
    return JsonResponse({'slots': list(slots)}, json_dumps_params={'default': str})
