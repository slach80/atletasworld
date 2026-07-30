from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Q
from django.views.decorators.http import require_POST
from clients.models import Client, ClientCredit, ClientPackage
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_credits(request):
    """Manage client credits — view, grant, and apply credits."""
    from django.utils import timezone as tz

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'grant':
            client_id = request.POST.get('client_id')
            amount = request.POST.get('amount', '').strip()
            credit_type = request.POST.get('credit_type', 'manual')
            notes = request.POST.get('notes', '')
            expires_str = request.POST.get('expires_at', '').strip()

            try:
                client = Client.objects.get(pk=client_id)
                from decimal import Decimal
                credit = ClientCredit.objects.create(
                    client=client,
                    amount=Decimal(amount),
                    credit_type=credit_type,
                    notes=notes,
                    expires_at=expires_str or None,
                    created_by=request.user,
                )
                messages.success(request, f'${credit.amount} credit granted to {client.user.get_full_name() or client.user.username}.')
            except Exception as e:
                messages.error(request, f'Error granting credit: {e}')

        elif action == 'cancel':
            credit_id = request.POST.get('credit_id')
            credit = get_object_or_404(ClientCredit, pk=credit_id)
            if credit.status == 'available':
                credit.status = 'cancelled'
                credit.save()
                messages.success(request, 'Credit cancelled.')
            else:
                messages.error(request, 'Only available credits can be cancelled.')

        return redirect('owner_credits')

    # Summary: clients with APC Select packages + credit balances
    today = tz.now().date()
    select_members = ClientPackage.objects.filter(
        package__package_type='select',
        status='active',
        expiry_date__gte=today,
    ).select_related('client__user', 'package').order_by('client__user__first_name')

    # All credits (paginated by most recent)
    all_credits = ClientCredit.objects.select_related(
        'client__user', 'source_package__package', 'applied_to__package', 'created_by'
    ).order_by('-created_at')[:200]

    # Available credit totals per client — DB aggregate instead of Python loop
    client_balances = dict(
        ClientCredit.objects.filter(
            status='available'
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.localdate())
        ).values('client_id').annotate(total=Sum('amount')).values_list('client_id', 'total')
    )

    clients_with_credits = Client.objects.filter(
        credits__status='available'
    ).distinct().select_related('user')

    context = {
        'select_members': select_members,
        'all_credits': all_credits,
        'client_balances': client_balances,
        'clients_with_credits': clients_with_credits,
        'all_clients': Client.objects.select_related('user').order_by('user__first_name'),
        'credit_type_choices': ClientCredit.CREDIT_TYPE_CHOICES,
    }
    return render(request, 'owner/credits.html', context)
