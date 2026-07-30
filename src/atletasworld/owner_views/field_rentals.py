from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Sum, Q
from django.views.decorators.http import require_POST
from coaches.models import ScheduleBlock
from clients.models import FieldRentalSlot, RentalService, Client
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_field_slots(request):
    """List and create rental slots. Also handles service catalog CRUD."""
    from clients.models import FieldRentalSlot, RentalService, Notification, Client
    from datetime import datetime as dt

    today = timezone.localdate()

    # --- Service catalog actions (merged from owner_services) ---
    action = request.POST.get('action', '')
    if request.method == 'POST' and action == 'service_create':
        try:
            RentalService.objects.create(
                name=request.POST['name'],
                service_type=request.POST['service_type'],
                description=request.POST.get('description', ''),
                capacity=request.POST.get('capacity') or None,
                price=request.POST['price'],
                pricing_type=request.POST.get('pricing_type', 'flat'),
                requires_approval=request.POST.get('requires_approval') == 'on',
                is_active=True,
            )
            messages.success(request, 'Service added.')
        except Exception as e:
            messages.error(request, f'Error creating service: {e}')
        return redirect('owner_field_slots')

    if request.method == 'POST' and action == 'service_save':
        svc = get_object_or_404(RentalService, pk=request.POST.get('service_id'))
        try:
            svc.name = request.POST['name']
            svc.service_type = request.POST['service_type']
            svc.description = request.POST.get('description', '')
            svc.capacity = request.POST.get('capacity') or None
            svc.price = request.POST['price']
            svc.pricing_type = request.POST.get('pricing_type', 'flat')
            svc.requires_approval = request.POST.get('requires_approval') == 'on'
            svc.is_active = request.POST.get('is_active') == 'on'
            svc.save()
            messages.success(request, f'"{svc.name}" updated.')
        except Exception as e:
            messages.error(request, f'Error updating service: {e}')
        return redirect('owner_field_slots')

    if request.method == 'POST' and action == 'service_delete':
        svc = get_object_or_404(RentalService, pk=request.POST.get('service_id'))
        active_slots = svc.slots.filter(status__in=['pending_approval', 'booked']).count()
        if active_slots:
            messages.error(request, f'Cannot delete: {active_slots} active slot(s) use this service.')
        else:
            svc.delete()
            messages.success(request, 'Service deleted.')
        return redirect('owner_field_slots')

    if request.method == 'POST' and action == 'add':
        try:
            start_str = request.POST.get('start_time', '')
            end_str    = request.POST.get('end_time', '')
            start_t    = dt.strptime(start_str, '%H:%M').time()
            end_t      = dt.strptime(end_str,   '%H:%M').time()
            duration   = int((dt.combine(today, end_t) - dt.combine(today, start_t)).seconds / 60)
            service_id = request.POST.get('service_id') or None
            service    = RentalService.objects.get(pk=service_id) if service_id else None

            slot = FieldRentalSlot.objects.create(
                date=request.POST.get('date'),
                start_time=start_t,
                end_time=end_t,
                duration_minutes=duration,
                price=request.POST.get('price', 0),
                title=request.POST.get('title', ''),
                notes=request.POST.get('notes', ''),
                service=service,
            )
            if slot.has_conflicting_schedule_blocks:
                messages.warning(request,
                    f'Slot created, but existing coach schedule blocks overlap this time. '
                    f'Those blocks will be blocked from new bookings once a field rental is active.')
            else:
                messages.success(request, f'Field rental slot created for {slot.date}.')
        except Exception as e:
            messages.error(request, f'Error creating slot: {e}')
        return redirect('owner_field_slots')

    status_filter = request.GET.get('status', 'all')
    slots = FieldRentalSlot.objects.select_related('booked_by_client__user', 'booked_by_team')
    if status_filter != 'all':
        slots = slots.filter(status=status_filter)
    slots = slots.order_by('date', 'start_time')

    pending_slots = FieldRentalSlot.objects.filter(status='pending_approval').order_by('requested_at')
    revenue = FieldRentalSlot.objects.filter(
        status='booked', date__month=today.month, date__year=today.year, payment_status='paid'
    ).aggregate(total=Sum('amount_paid'))['total'] or 0

    from django.db.models import Prefetch
    status_filter_q = slots  # already filtered above

    # Services with their slots prefetched (filtered by status if set)
    slot_qs = FieldRentalSlot.objects.select_related(
        'booked_by_client__user', 'booked_by_team'
    ).order_by('date', 'start_time')
    if status_filter != 'all':
        slot_qs = slot_qs.filter(status=status_filter)

    services_with_slots = RentalService.objects.prefetch_related(
        Prefetch('slots', queryset=slot_qs, to_attr='filtered_slots')
    ).order_by('service_type', 'name')

    # Slots not linked to any service
    unlinked_slots = FieldRentalSlot.objects.filter(
        service__isnull=True
    ).select_related('booked_by_client__user', 'booked_by_team').order_by('date', 'start_time')
    if status_filter != 'all':
        unlinked_slots = unlinked_slots.filter(status=status_filter)

    context = {
        'slots': slots,
        'pending_slots': pending_slots,
        'status_filter': status_filter,
        'today': today,
        'statuses': [('available', 'Available'), ('pending_approval', 'Pending'), ('booked', 'Booked'), ('cancelled', 'Cancelled')],
        **FieldRentalSlot.objects.aggregate(
            available_count=Count('id', filter=Q(status='available', date__gte=today)),
            pending_count=Count('id', filter=Q(status='pending_approval')),
            booked_month=Count('id', filter=Q(status='booked', date__month=today.month, date__year=today.year)),
        ),
        'revenue_month':   revenue,
        'services':             RentalService.objects.filter(is_active=True).order_by('service_type', 'name'),
        'all_services':         RentalService.objects.all().order_by('service_type', 'name'),
        'services_with_slots':  services_with_slots,
        'unlinked_slots':       unlinked_slots,
        'service_type_choices': RentalService.SERVICE_TYPE_CHOICES,
        'pricing_type_choices': RentalService.PRICING_TYPE_CHOICES,
    }
    return render(request, 'owner/field_slots.html', context)


@login_required
@user_passes_test(is_owner)
def owner_field_slot_edit(request, pk):
    """Edit an available field rental slot."""
    from clients.models import FieldRentalSlot
    from datetime import datetime as dt

    slot = get_object_or_404(FieldRentalSlot, pk=pk)
    if slot.status != 'available':
        messages.error(request, 'Only available (unbooked) slots can be edited.')
        return redirect('owner_field_slots')

    if request.method == 'POST':
        try:
            today = timezone.localdate()
            start_t = dt.strptime(request.POST['start_time'], '%H:%M').time()
            end_t   = dt.strptime(request.POST['end_time'],   '%H:%M').time()
            slot.date             = request.POST['date']
            slot.start_time       = start_t
            slot.end_time         = end_t
            slot.duration_minutes = int((dt.combine(today, end_t) - dt.combine(today, start_t)).seconds / 60)
            slot.price            = request.POST['price']
            slot.title            = request.POST.get('title', '')
            slot.notes            = request.POST.get('notes', '')
            slot.save()
            messages.success(request, 'Slot updated.')
        except Exception as e:
            messages.error(request, f'Error updating slot: {e}')
    return redirect('owner_field_slots')


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_field_slot_approve(request, pk):
    """Approve a pending field rental request."""
    from clients.models import FieldRentalSlot, Notification

    slot = get_object_or_404(FieldRentalSlot, pk=pk, status='pending_approval')
    slot.status      = 'booked'
    slot.approved_at = timezone.now()
    slot.booked_at   = timezone.now()
    slot.save()

    # Notify requester
    if slot.booked_by_client:
        Notification.objects.create(
            client=slot.booked_by_client,
            notification_type='field_rental_approved',
            title='Field Rental Approved!',
            message=f'Your field rental request for {slot.date:%b %d, %Y} '
                    f'({slot.start_time:%I:%M %p}–{slot.end_time:%I:%M %p}) has been approved.',
            method='email',
        )

    messages.success(request, f'Field rental approved for {slot.requester_name}.')
    return redirect('owner_field_slots')


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_field_slot_reject(request, pk):
    """Reject a pending field rental request."""
    from clients.models import FieldRentalSlot, Notification

    slot = get_object_or_404(FieldRentalSlot, pk=pk, status='pending_approval')
    reason = request.POST.get('rejection_reason', 'No reason provided.')

    requesting_client = slot.booked_by_client

    slot.status           = 'available'
    slot.rejection_reason = reason
    slot.rejected_at      = timezone.now()
    slot.booked_by_client = None
    slot.booked_by_team   = None
    slot.booker_type      = None
    slot.requested_at     = None
    slot.client_notes     = ''
    slot.save()

    if requesting_client:
        Notification.objects.create(
            client=requesting_client,
            notification_type='field_rental_rejected',
            title='Field Rental Not Approved',
            message=f'Your field rental request for {slot.date:%b %d, %Y} was not approved. Reason: {reason}',
            method='email',
        )

    messages.warning(request, 'Field rental request rejected and slot returned to available.')
    return redirect('owner_field_slots')


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_field_slot_cancel(request, pk):
    """Owner cancels a confirmed field rental booking."""
    from clients.models import FieldRentalSlot, Notification

    slot = get_object_or_404(FieldRentalSlot, pk=pk, status='booked')
    note = request.POST.get('cancellation_notes', '')
    requesting_client = slot.booked_by_client

    slot.status             = 'available'
    slot.cancellation_notes = note
    slot.cancelled_at       = timezone.now()
    slot.booked_by_client   = None
    slot.booked_by_team     = None
    slot.booker_type        = None
    slot.approved_at        = None
    slot.booked_at          = None
    slot.save()

    if requesting_client:
        Notification.objects.create(
            client=requesting_client,
            notification_type='field_rental_cancelled',
            title='Field Rental Cancelled',
            message=f'Your field rental on {slot.date:%b %d, %Y} '
                    f'({slot.start_time:%I:%M %p}–{slot.end_time:%I:%M %p}) has been cancelled by the owner.'
                    + (f' Note: {note}' if note else ''),
            method='email',
        )

    messages.warning(request, 'Field rental booking cancelled and slot returned to available.')
    return redirect('owner_field_slots')


@login_required
@user_passes_test(is_owner)
def owner_field_slot_conflict_check(request):
    """AJAX: check for ScheduleBlock conflicts and same-service slot conflicts."""
    from django.http import JsonResponse
    from clients.models import FieldRentalSlot

    date       = request.GET.get('date')
    start_time = request.GET.get('start_time')
    end_time   = request.GET.get('end_time')
    service_id = request.GET.get('service_id') or None
    exclude_pk = request.GET.get('exclude_pk') or None

    if not all([date, start_time, end_time]):
        return JsonResponse({'conflict': False, 'count': 0, 'blocks': [], 'service_conflicts': []})

    # Coach schedule block conflicts (relevant for field types)
    conflicts = ScheduleBlock.objects.filter(
        date=date, status__in=['available', 'booked']
    ).exclude(
        end_time__lte=start_time
    ).exclude(
        start_time__gte=end_time
    ).select_related('coach__user')

    blocks = [
        {
            'coach': f"{b.coach.user.first_name} {b.coach.user.last_name}".strip(),
            'start': str(b.start_time),
            'end':   str(b.end_time),
            'type':  b.get_session_type_display(),
        }
        for b in conflicts
    ]

    # Same-service slot conflicts
    service_conflict_list = []
    if service_id:
        svc_conflicts = FieldRentalSlot.check_service_blocked(
            service_id=service_id,
            date=date,
            start_time=start_time,
            end_time=end_time,
            exclude_pk=exclude_pk,
        ).select_related('booked_by_client__user', 'booked_by_team')
        service_conflict_list = [
            {
                'start':    str(s.start_time),
                'end':      str(s.end_time),
                'status':   s.status,
                'booker':   s.requester_name,
            }
            for s in svc_conflicts
        ]

    return JsonResponse({
        'conflict':          conflicts.exists(),
        'count':             conflicts.count(),
        'blocks':            blocks,
        'service_conflicts': service_conflict_list,
    })
