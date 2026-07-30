from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.views.decorators.http import require_POST
from clients.models import Package, DiscountCode, DiscountCodeUse
from bookings.models import SessionType
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_discount_codes(request):
    """Manage promotional discount codes."""
    from clients.models import DiscountCode, DiscountCodeUse
    from bookings.models import SessionType

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create':
            try:
                code_str = request.POST.get('code', '').strip().upper()
                if not code_str:
                    messages.error(request, 'Code cannot be blank.')
                    return redirect('owner_discount_codes')
                dc = DiscountCode.objects.create(
                    code=code_str,
                    description=request.POST.get('description', '').strip(),
                    discount_type=request.POST.get('discount_type'),
                    value=request.POST.get('value'),
                    scope=request.POST.get('scope', 'all'),
                    max_uses=request.POST.get('max_uses') or None,
                    max_uses_per_client=int(request.POST.get('max_uses_per_client') or 1),
                    min_purchase_amount=request.POST.get('min_purchase_amount') or None,
                    valid_from=request.POST.get('valid_from') or None,
                    valid_until=request.POST.get('valid_until') or None,
                    is_active=True,
                    created_by=request.user,
                )
                pkg_ids = request.POST.getlist('specific_packages')
                if pkg_ids:
                    dc.specific_packages.set(pkg_ids)
                st_ids = request.POST.getlist('specific_session_types')
                if st_ids:
                    dc.specific_session_types.set(st_ids)
                messages.success(request, f'Discount code "{dc.code}" created.')
            except Exception as e:
                messages.error(request, f'Error creating code: {e}')

        elif action == 'edit':
            pk = request.POST.get('code_id')
            dc = get_object_or_404(DiscountCode, pk=pk)
            try:
                dc.description         = request.POST.get('description', '').strip()
                dc.discount_type       = request.POST.get('discount_type')
                dc.value               = request.POST.get('value')
                dc.scope               = request.POST.get('scope', 'all')
                dc.max_uses            = request.POST.get('max_uses') or None
                dc.max_uses_per_client = int(request.POST.get('max_uses_per_client') or 1)
                dc.min_purchase_amount = request.POST.get('min_purchase_amount') or None
                dc.valid_from          = request.POST.get('valid_from') or None
                dc.valid_until         = request.POST.get('valid_until') or None
                dc.save()
                dc.specific_packages.set(request.POST.getlist('specific_packages'))
                dc.specific_session_types.set(request.POST.getlist('specific_session_types'))
                messages.success(request, f'Code "{dc.code}" updated.')
            except Exception as e:
                messages.error(request, f'Error updating code: {e}')

        elif action == 'toggle':
            dc = get_object_or_404(DiscountCode, pk=request.POST.get('code_id'))
            dc.is_active = not dc.is_active
            dc.save(update_fields=['is_active'])
            messages.success(request, f'Code {dc.code} {"activated" if dc.is_active else "deactivated"}.')

        elif action == 'delete':
            dc = get_object_or_404(DiscountCode, pk=request.POST.get('code_id'))
            if dc.uses.filter(status='applied').exists():
                messages.error(request, f'Cannot delete "{dc.code}" — it has been used. Deactivate it instead.')
            else:
                code_str = dc.code
                dc.delete()
                messages.success(request, f'Discount code "{code_str}" deleted.')

        return redirect('owner_discount_codes')

    _AUTO_CODES = ['SIBLING-AUTO']
    codes = DiscountCode.objects.exclude(code__in=_AUTO_CODES)\
        .prefetch_related('uses', 'specific_packages', 'specific_session_types').order_by('-created_at')
    sibling_dc = DiscountCode.objects.filter(code='SIBLING-AUTO').first()
    context = {
        'codes': codes,
        'sibling_dc': sibling_dc,
        'all_packages': Package.objects.filter(is_active=True).order_by('price'),
        'all_session_types': SessionType.objects.filter(is_active=True).order_by('name'),
    }
    return render(request, 'owner/discount_codes.html', context)


@login_required
@user_passes_test(is_owner)
def owner_discount_code_detail(request, pk):
    """Usage log for a specific discount code."""
    from clients.models import DiscountCode
    dc = get_object_or_404(DiscountCode, pk=pk)
    uses = dc.uses.select_related(
        'client__user', 'applied_to_package__package', 'applied_to_booking__session_type'
    ).order_by('-used_at')
    return render(request, 'owner/discount_code_detail.html', {'code': dc, 'uses': uses})
