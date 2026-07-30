from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Count, Q
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_packages(request):
    """List all packages with management options."""
    from clients.models import Package, ClientPackage
    from django.db.models import Count

    base_qs = Package.objects.annotate(
        active_purchases=Count('clientpackage', filter=Q(clientpackage__status='active')),
        total_purchases=Count('clientpackage')
    )
    packages         = base_qs.filter(is_active=True).order_by('price')
    archived_packages= base_qs.filter(is_active=False).order_by('price')

    context = {
        'packages': packages,
        'archived_packages': archived_packages,
    }
    return render(request, 'owner/packages.html', context)


@login_required
@user_passes_test(is_owner)
def owner_package_add(request):
    """Add a new package."""
    from clients.models import Package

    if request.method == 'POST':
        try:
            package = Package.objects.create(
                name=request.POST.get('name'),
                package_type=request.POST.get('package_type'),
                description=request.POST.get('description', ''),
                price=request.POST.get('price'),
                stripe_price_id=request.POST.get('stripe_price_id', '').strip(),
                billing_tier=request.POST.get('billing_tier', ''),
                program_group=request.POST.get('program_group', '').strip(),
                sessions_included=request.POST.get('sessions_included', 0),
                validity_weeks=request.POST.get('validity_weeks', 4),
                is_active=request.POST.get('is_active') == 'on',
                is_purchasable=request.POST.get('is_purchasable') == 'on',
                is_special=request.POST.get('is_special') == 'on',
                max_participants=request.POST.get('max_participants', 0),
                age_group=request.POST.get('age_group', ''),
                event_start_date=request.POST.get('event_start_date') or None,
                event_start_time=request.POST.get('event_start_time') or None,
                event_end_date=request.POST.get('event_end_date') or None,
                event_end_time=request.POST.get('event_end_time') or None,
                event_location=request.POST.get('event_location', ''),
            )
            messages.success(request, f'Package "{package.name}" created successfully!')
            return redirect('owner_packages')
        except Exception as e:
            messages.error(request, f'Error creating package: {str(e)}')

    context = {
        'package_types': Package.PACKAGE_TYPE_CHOICES,
    }
    return render(request, 'owner/package_form.html', context)


@login_required
@user_passes_test(is_owner)
def owner_package_edit(request, pk):
    """Edit an existing package."""
    from clients.models import Package
    from django.shortcuts import get_object_or_404

    package = get_object_or_404(Package, pk=pk)

    if request.method == 'POST':
        try:
            package.name = request.POST.get('name')
            package.package_type = request.POST.get('package_type')
            package.description = request.POST.get('description', '')
            package.price = request.POST.get('price')
            package.stripe_price_id = request.POST.get('stripe_price_id', '').strip()
            package.billing_tier = request.POST.get('billing_tier', '')
            package.program_group = request.POST.get('program_group', '').strip()
            package.sessions_included = request.POST.get('sessions_included', 0)
            package.validity_weeks = request.POST.get('validity_weeks', 4)
            package.is_active      = request.POST.get('is_active') == 'on'
            package.is_purchasable = request.POST.get('is_purchasable') == 'on'
            package.is_special     = request.POST.get('is_special') == 'on'
            package.max_participants = request.POST.get('max_participants', 0)
            package.age_group = request.POST.get('age_group', '')
            package.event_start_date = request.POST.get('event_start_date') or None
            package.event_start_time = request.POST.get('event_start_time') or None
            package.event_end_date = request.POST.get('event_end_date') or None
            package.event_end_time = request.POST.get('event_end_time') or None
            package.event_location = request.POST.get('event_location', '')
            package.save()
            messages.success(request, f'Package "{package.name}" updated successfully!')
            return redirect('owner_packages')
        except Exception as e:
            messages.error(request, f'Error updating package: {str(e)}')

    context = {
        'package': package,
        'package_types': Package.PACKAGE_TYPE_CHOICES,
        'editing': True,
    }
    return render(request, 'owner/package_form.html', context)


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_package_delete(request, pk):
    """Archive a package (soft delete — sets is_active=False)."""
    from clients.models import Package
    from django.shortcuts import get_object_or_404

    package = get_object_or_404(Package, pk=pk)
    package.is_active = False
    package.save()
    messages.success(request, f'Package "{package.name}" archived.')
    return redirect('owner_packages')


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_package_restore(request, pk):
    """Restore an archived package."""
    from clients.models import Package
    from django.shortcuts import get_object_or_404

    package = get_object_or_404(Package, pk=pk)
    package.is_active = True
    package.save()
    messages.success(request, f'Package "{package.name}" restored.')
    return redirect('owner_packages')


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_package_hard_delete(request, pk):
    """Permanently delete a package (only if no active client purchases)."""
    from clients.models import Package, ClientPackage
    from django.shortcuts import get_object_or_404

    package = get_object_or_404(Package, pk=pk)
    active_count = ClientPackage.objects.filter(package=package, status='active').count()
    if active_count > 0:
        messages.error(request, f'Cannot delete "{package.name}" — {active_count} active purchase(s) exist. Archive it instead.')
    else:
        name = package.name
        package.delete()
        messages.success(request, f'Package "{name}" permanently deleted.')
    return redirect('owner_packages')


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_package_duplicate(request, pk):
    """Duplicate a package."""
    from clients.models import Package
    from django.shortcuts import get_object_or_404

    orig = get_object_or_404(Package, pk=pk)
    copy = Package.objects.create(
        name=f'{orig.name} (Copy)',
        package_type=orig.package_type,
        description=orig.description,
        price=orig.price,
        sessions_included=orig.sessions_included,
        validity_weeks=orig.validity_weeks,
        is_active=False,  # start archived so owner can review before publishing
        is_special=orig.is_special,
        age_group=orig.age_group,
        max_participants=orig.max_participants,
    )
    messages.success(request, f'Package duplicated as "{copy.name}". Review and activate when ready.')
    return redirect('owner_package_edit', pk=copy.pk)


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_package_assign(request, pk):
    """Assign or reassign a package to a specific player (AJAX endpoint)."""
    import json
    from django.shortcuts import get_object_or_404
    from clients.models import ClientPackage, Player
    from django.http import JsonResponse

    try:
        package = get_object_or_404(ClientPackage, pk=pk)
        data = json.loads(request.body)
        player_id = data.get('player_id')

        if player_id:
            # Verify player belongs to the same client
            player = get_object_or_404(Player, pk=player_id, client=package.client, is_active=True)
            package.player = player
        else:
            # Unassign package
            package.player = None

        package.save()

        return JsonResponse({
            'success': True,
            'message': f'Package assigned to {package.player.first_name}' if package.player else 'Package unassigned'
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@user_passes_test(is_owner)
def owner_package_adjust(request, pk):
    """Manually adjust sessions_remaining on a ClientPackage (owner only)."""
    import json
    from clients.models import ClientPackage
    try:
        package = get_object_or_404(ClientPackage, pk=pk)
        data = json.loads(request.body)
        new_remaining = int(data['sessions_remaining'])
        if new_remaining < 0 or (package.package.sessions_included > 0 and new_remaining > package.package.sessions_included):
            return JsonResponse({'error': 'Value out of range'}, status=400)
        package.sessions_remaining = new_remaining
        package.sessions_used = package.package.sessions_included - new_remaining
        if new_remaining == 0:
            package.status = 'exhausted'
        elif package.status == 'exhausted':
            package.status = 'active'
        package.save()
        return JsonResponse({'success': True, 'sessions_remaining': new_remaining})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
