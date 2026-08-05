from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.db.models import Sum, Q
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone

from clients.models import Client, Player, Package, ClientPackage


@login_required
@require_POST
def package_payment_intent(request, package_id):
    """Proxy to payments app — create PaymentIntent for one-time package purchase."""
    from payments.views import create_package_payment_intent
    return create_package_payment_intent(request, package_id)


@login_required
@require_POST
def batch_package_payment_intent(request):
    """Proxy to payments app — create PaymentIntent for batch package purchase (multiple players)."""
    from payments.views import create_batch_package_payment_intent
    return create_batch_package_payment_intent(request)


@login_required
@require_POST
def select_setup_intent(request):
    """Create a Stripe SetupIntent to collect a card for Select subscription."""
    from django.http import JsonResponse as _JsonResponse
    from django.conf import settings as _s
    import stripe as _stripe_lib
    from payments.views import _get_or_create_stripe_customer

    if not _s.STRIPE_SECRET_KEY:
        return _JsonResponse({'error': 'Payments not configured.'}, status=503)

    _stripe_lib.api_key = _s.STRIPE_SECRET_KEY
    client, _ = Client.objects.get_or_create(user=request.user)
    try:
        customer_id = _get_or_create_stripe_customer(client)
        si = _stripe_lib.SetupIntent.create(
            customer=customer_id,
            usage='off_session',
        )
        return _JsonResponse({'client_secret': si.client_secret})
    except _stripe_lib.error.StripeError as e:
        return _JsonResponse({'error': str(e.user_message)}, status=400)


@login_required
@require_POST
def package_subscribe(request, package_id):
    """Proxy to payments app — create Stripe Subscription for recurring package."""
    from payments.views import create_package_subscription
    return create_package_subscription(request, package_id)


@login_required
@require_POST
def select_update_payment_method(request):
    """Replace the default payment method on the client's Stripe customer."""
    from django.http import JsonResponse as _JsonResponse
    from django.conf import settings as _s
    import stripe as _stripe_lib

    if not _s.STRIPE_SECRET_KEY:
        return _JsonResponse({'error': 'Payments not configured.'}, status=503)

    client, _ = Client.objects.get_or_create(user=request.user)
    payment_method_id = request.POST.get('payment_method_id', '').strip()
    if not payment_method_id:
        return _JsonResponse({'error': 'No payment method provided.'}, status=400)

    _stripe_lib.api_key = _s.STRIPE_SECRET_KEY
    try:
        if not client.stripe_customer_id:
            return _JsonResponse({'error': 'No billing account found. Please contact support.'}, status=400)
        _stripe_lib.PaymentMethod.attach(payment_method_id, customer=client.stripe_customer_id)
        _stripe_lib.Customer.modify(client.stripe_customer_id,
            invoice_settings={'default_payment_method': payment_method_id})
        return _JsonResponse({'ok': True})
    except _stripe_lib.error.StripeError as e:
        return _JsonResponse({'error': str(e.user_message)}, status=400)


@login_required
@require_POST
def select_cancel_subscription(request, client_package_id):
    """Cancel an APC Select Stripe subscription at period end."""
    from django.http import JsonResponse as _JsonResponse
    from django.conf import settings as _s
    import stripe as _stripe_lib

    client, _ = Client.objects.get_or_create(user=request.user)
    cp = get_object_or_404(ClientPackage, pk=client_package_id, client=client,
                           package__package_type='select', status='active')

    if not cp.stripe_subscription_id:
        return _JsonResponse({'error': 'No active subscription found. Contact us to cancel.'}, status=400)

    if not _s.STRIPE_SECRET_KEY:
        return _JsonResponse({'error': 'Payments not configured.'}, status=503)

    try:
        _stripe_lib.api_key = _s.STRIPE_SECRET_KEY
        _stripe_lib.Subscription.modify(cp.stripe_subscription_id, cancel_at_period_end=True)
        messages.success(request, 'Your APC Select membership will not renew after the current period ends.')
    except _stripe_lib.error.StripeError as e:
        return _JsonResponse({'error': str(e.user_message)}, status=400)

    return redirect('clients:packages')


@login_required
@require_POST
def package_assign(request, package_id):
    """Assign or reassign a package to a specific player (AJAX endpoint for client portal)."""
    import json

    try:
        client, _ = Client.objects.get_or_create(user=request.user)
        package = get_object_or_404(ClientPackage, pk=package_id, client=client)
        data = json.loads(request.body)
        player_id = data.get('player_id')

        if player_id:
            # Verify player belongs to the same client
            player = get_object_or_404(Player, pk=player_id, client=client, is_active=True)
            package.player = player

            # This package's own select_monthly credits may have been granted before a
            # player was assigned (player is unset at Stripe webhook time). Attribute them
            # to the now-known player before saving, so the seed_select_credits signal's
            # per-player guard sees them and doesn't grant a duplicate batch.
            if package.package.package_type == 'select':
                from clients.models import ClientCredit
                ClientCredit.objects.filter(
                    source_package=package, credit_type='select_monthly', player__isnull=True,
                ).update(player=player)
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
def packages_list(request):
    """List all packages for the client."""
    client, created = Client.objects.get_or_create(user=request.user)
    today = timezone.localdate()

    # Require at least one player before purchasing
    if not client.players.filter(is_active=True).exists():
        messages.info(request, 'Please add a player before purchasing a package.')
        return redirect(f"{reverse('clients:player_add')}?next={reverse('clients:packages')}")

    active_packages = client.packages.filter(
        status='active',
        expiry_date__gte=timezone.localdate()
    )

    expired_packages = client.packages.exclude(
        status='active',
        expiry_date__gte=timezone.localdate()
    )

    # Separate select membership from regular packages — only shown to invited clients
    select_packages = Package.objects.filter(is_active=True, is_purchasable=True, package_type='select').order_by('price') if client.select_invited else Package.objects.none()
    _all_purchasable = Package.objects.filter(
        is_active=True, is_purchasable=True, program_group=''
    ).exclude(package_type__in=['team', 'select']).order_by('price')

    # Partition into display sections
    import datetime as _dt
    _fall_start = _dt.date(2026, 8, 17)
    _summer_end = _dt.date(2026, 8, 16)

    summer_packages  = [p for p in _all_purchasable if 'summer' in p.name.lower()]
    kcfc_packages    = [p for p in _all_purchasable if 'kcfc'   in p.name.lower()]
    # Fall flat packages — have Fall dates but no program_group (Basic 4/8 Fall etc.)
    fall_flat_packages = [p for p in _all_purchasable
                          if p.event_start_date and p.event_start_date >= _fall_start
                          and 'summer' not in p.name.lower()
                          and 'kcfc' not in p.name.lower()]
    special_packages = Package.objects.filter(
        is_active=True, is_purchasable=True, is_special=True
    ).order_by('event_start_date')
    _grouped_ids = ({p.pk for p in summer_packages} | {p.pk for p in kcfc_packages}
                    | {p.pk for p in fall_flat_packages})
    _special_ids = set(special_packages.values_list('pk', flat=True))
    other_packages   = [p for p in _all_purchasable
                        if p.pk not in _grouped_ids and p.pk not in _special_ids]
    available_packages = list(_all_purchasable)  # kept for any legacy template references

    # Fall program groups — packages sharing a program_group shown as a single card with billing picker
    _grouped_qs = Package.objects.filter(
        is_active=True, is_purchasable=True, program_group__gt=''
    ).order_by('program_group', 'price')
    fall_program_groups = {}
    for _pkg in _grouped_qs:
        fall_program_groups.setdefault(_pkg.program_group, []).append(_pkg)

    has_select_membership = active_packages.filter(package__package_type='select').exists()
    # Sibling discount: client already has an active recurring Select subscription
    has_select_sibling_sub = active_packages.filter(
        package__package_type='select', stripe_subscription_id__gt=''
    ).exists()
    select_credit_balance = client.credits.filter(
        status='available'
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=today)
    ).aggregate(total=Sum('amount'))['total'] or 0 if has_select_membership else 0

    players = client.players.filter(is_active=True)
    unassigned_packages = [p for p in active_packages if not p.player_id]
    single_player = players.first() if unassigned_packages and players.count() == 1 else None

    from django.conf import settings as django_settings
    context = {
        'client': client,
        'players': players,
        'active_packages': active_packages,
        'expired_packages': expired_packages,
        'available_packages': available_packages,
        'summer_packages': summer_packages,
        'kcfc_packages': kcfc_packages,
        'fall_flat_packages': fall_flat_packages,
        'special_packages': special_packages,
        'other_packages': other_packages,
        'select_packages': select_packages,
        'fall_program_groups': fall_program_groups,
        'has_select_membership': has_select_membership,
        'has_select_sibling_sub': has_select_sibling_sub,
        'select_credit_balance': select_credit_balance,
        'stripe_public_key': django_settings.STRIPE_PUBLIC_KEY,
        'unassigned_packages': unassigned_packages,
        'single_player': single_player,
    }
    return render(request, 'clients/packages.html', context)
