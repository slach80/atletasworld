from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_services(request):
    """Redirect to rentals page — service catalog is now embedded there."""
    return redirect('owner_field_slots')


@login_required
@user_passes_test(is_owner)
def owner_service_edit(request, pk):
    """Edit an existing service catalog entry."""
    from clients.models import RentalService
    service = get_object_or_404(RentalService, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete':
            active_slots = service.slots.filter(status__in=['pending_approval', 'booked']).count()
            if active_slots:
                messages.error(request, f'Cannot delete: {active_slots} active slot(s) use this service.')
            else:
                service.delete()
                messages.success(request, 'Service deleted.')
            return redirect('owner_services')

        try:
            service.name             = request.POST['name']
            service.service_type     = request.POST['service_type']
            service.description      = request.POST.get('description', '')
            service.capacity         = request.POST.get('capacity') or None
            service.price            = request.POST['price']
            service.pricing_type     = request.POST.get('pricing_type', 'flat')
            service.requires_approval = request.POST.get('requires_approval') == 'on'
            service.is_active        = request.POST.get('is_active') == 'on'
            service.save()
            messages.success(request, f'"{service.name}" updated.')
        except Exception as e:
            messages.error(request, f'Error updating service: {e}')
        return redirect('owner_services')

    context = {
        'service': service,
        'service_type_choices': RentalService.SERVICE_TYPE_CHOICES,
        'pricing_type_choices': RentalService.PRICING_TYPE_CHOICES,
    }
    return render(request, 'owner/service_edit.html', context)
