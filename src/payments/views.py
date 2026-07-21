"""
Stripe payment views for Atletas Performance Center.

Flows:
  1. create_package_payment_intent  — one-time package purchase
  2. create_package_subscription     — recurring subscription
  3. payments_webhook                — Stripe event handler (single source of truth)
  4. rental_pay (stub)               — facility rental payment (wired after keys)
"""
import stripe
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404

from django.utils import timezone
from clients.models import Client, Package, ClientPackage
from payments.models import Payment
from payments.stripe_utils import get_stripe as _stripe, get_or_create_stripe_customer as _get_or_create_stripe_customer

logger = logging.getLogger(__name__)


# ── One-time package purchase ─────────────────────────────────────────────────

@login_required
@require_POST
def create_package_payment_intent(request, package_id):
    """Create a Stripe PaymentIntent for a one-time package purchase."""
    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({'error': 'Payments not yet configured.'}, status=503)

    from decimal import Decimal
    from clients.models import DiscountCode, DiscountCodeUse

    package = get_object_or_404(Package, pk=package_id, is_active=True)
    client, _ = Client.objects.get_or_create(user=request.user)
    s = _stripe()

    subtotal = package.price

    # --- Player selection (for sibling discount detection) ---
    player_id_str = request.POST.get('player_id') or None
    player_id_int = int(player_id_str) if player_id_str and player_id_str.isdigit() else None

    # --- Sibling discount: same exact package already active for another player ---
    sibling_discount_amount = Decimal('0.00')
    sibling_discount_found  = False
    if player_id_int:
        sibling_has_package = client.packages.filter(
            package=package,
            status='active',
        ).exclude(player_id=player_id_int).exists()
    else:
        # No player selected — sibling discount if client already has same package active
        sibling_has_package = client.packages.filter(
            package=package,
            status='active',
        ).exists()
    if sibling_has_package:
        sibling_discount_amount = (subtotal * Decimal('50') / Decimal('100')).quantize(Decimal('0.01'))
        sibling_discount_found = True

    # --- Promo code (atomic check to prevent race on max_uses_per_client) ---
    promo_code_str  = request.POST.get('promo_code', '').strip().upper()
    discount_code   = None
    discount_amount = Decimal('0.00')
    if promo_code_str and not sibling_discount_found:
        try:
            with transaction.atomic():
                dc = DiscountCode.objects.select_for_update().get(code=promo_code_str, is_active=True)
                ok, _ = dc.is_valid_now()
                if ok and dc.scope in ('all', 'packages'):
                    if dc.specific_packages.exists() and not dc.specific_packages.filter(pk=package.pk).exists():
                        pass  # code not valid for this specific package
                    elif dc.min_purchase_amount and subtotal < dc.min_purchase_amount:
                        pass  # minimum not met
                    else:
                        client_uses = dc.uses.filter(client=client, status='applied').count()
                        if client_uses < dc.max_uses_per_client:
                            discount_amount = dc.compute_discount(subtotal)
                            discount_code = dc
        except DiscountCode.DoesNotExist:
            pass

    # --- APC Select credit ---
    credit_applied  = Decimal('0.00')
    apply_credit    = request.POST.get('apply_credit') == '1'
    if apply_credit:
        remaining = subtotal - discount_amount
        for credit in client.credits.filter(status='available').order_by('expires_at'):
            if credit.is_usable and remaining > 0:
                use_amount = min(credit.amount, remaining)
                credit_applied += use_amount
                remaining -= use_amount

    # Sibling discount takes precedence over promo code (use whichever is larger)
    effective_discount = max(discount_amount, sibling_discount_amount)
    if sibling_discount_found:
        discount_amount = sibling_discount_amount  # use sibling for tracking
        discount_code   = None                     # don't double-record promo

    final_amount = max(subtotal - effective_discount - credit_applied, Decimal('0.00'))

    # Free order — 100% discount, skip Stripe entirely
    if final_amount == Decimal('0.00'):
        import uuid
        from clients.models import DiscountCodeUse
        free_intent_id = f'FREE-{uuid.uuid4().hex}'
        with transaction.atomic():
            Payment.objects.create(
                client=client,
                amount=Decimal('0.00'),
                stripe_payment_intent_id=free_intent_id,
                description=f'Package (free): {package.name}',
                status='succeeded',
            )
            if discount_code and effective_discount > 0:
                DiscountCodeUse.objects.create(
                    code=discount_code,
                    client=client,
                    discount_amount=effective_discount,
                    original_amount=subtotal,
                    final_amount=Decimal('0.00'),
                    status='pending',
                    stripe_payment_intent_id=free_intent_id,
                )
            _activate_package(
                client.pk, package.pk, free_intent_id,
                metadata={
                    'discount_code': promo_code_str or '',
                    'discount_amount': str(effective_discount),
                    'credit_applied': str(credit_applied),
                    'player_id': str(player_id_int or ''),
                },
            )
        return JsonResponse({
            'free': True,
            'amount': '0.00',
            'original_amount': str(subtotal),
            'discount_amount': str(effective_discount),
            'credit_applied': str(credit_applied),
            'package_name': package.name,
        })

    amount_cents = int(final_amount * 100)

    try:
        customer_id = _get_or_create_stripe_customer(client)
        intent = s.PaymentIntent.create(
            amount=amount_cents,
            currency='usd',
            customer=customer_id,
            metadata={
                'type': 'package_purchase',
                'package_id': str(package.pk),
                'client_id': str(client.pk),
                'discount_code': promo_code_str if not sibling_discount_found else 'SIBLING-AUTO',
                'discount_amount': str(effective_discount),
                'credit_applied': str(credit_applied),
                'sibling_discount': '1' if sibling_discount_found else '0',
            },
            description=f'Package: {package.name}',
        )

        # Pending Payment record — confirmed by webhook
        Payment.objects.create(
            client=client,
            amount=final_amount,
            stripe_payment_intent_id=intent.id,
            description=f'Package: {package.name}',
            status='pending',
        )

        # Track pending discount use — finalised by webhook on payment success
        if sibling_discount_found and sibling_discount_amount > 0:
            sibling_dc, _ = DiscountCode.objects.get_or_create(
                code='SIBLING-AUTO',
                defaults={
                    'description': 'Automatic sibling discount (50% off same package)',
                    'discount_type': 'percent',
                    'value': Decimal('50.00'),
                    'scope': 'all',
                    'max_uses': None,
                    'max_uses_per_client': 99,
                    'is_active': True,
                }
            )
            DiscountCodeUse.objects.create(
                code=sibling_dc,
                client=client,
                discount_amount=sibling_discount_amount,
                original_amount=subtotal,
                final_amount=final_amount,
                status='pending',
                stripe_payment_intent_id=intent.id,
            )
        elif discount_code and effective_discount > 0:
            DiscountCodeUse.objects.create(
                code=discount_code,
                client=client,
                discount_amount=effective_discount,
                original_amount=subtotal,
                final_amount=final_amount,
                status='pending',
                stripe_payment_intent_id=intent.id,
            )

        return JsonResponse({
            'client_secret': intent.client_secret,
            'amount': str(final_amount),
            'original_amount': str(subtotal),
            'discount_amount': str(effective_discount),
            'credit_applied': str(credit_applied),
            'sibling_discount': sibling_discount_found,
            'package_name': package.name,
        })

    except stripe.error.StripeError as e:
        logger.exception('PaymentIntent creation failed for package %s', package_id)
        return JsonResponse({'error': str(e.user_message)}, status=400)


# ── Multi-player batch package purchase ──────────────────────────────────────

@login_required
@require_POST
def create_batch_package_payment_intent(request):
    """Create a single Stripe PaymentIntent for purchasing packages for multiple players.

    Supports two request formats:
      1. Single-package (legacy): {package_id, player_ids, promo_code?, apply_credit?}
      2. Multi-package cart:      {items: [{package_id, player_ids}], promo_code?, apply_credit?}

    Sibling discount (50% off) applies per package when 2nd+ player in the family
    already has that same package active or is in the same batch.
    """
    import json
    from decimal import Decimal
    from clients.models import DiscountCode, DiscountCodeUse, Player

    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({'error': 'Payments not yet configured.'}, status=503)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    promo_code_str = (data.get('promo_code') or '').strip().upper()
    apply_credit = data.get('apply_credit', False)

    # Normalize input to items list: [{package_id, player_ids}]
    items_input = data.get('items')
    if not items_input:
        package_id = data.get('package_id')
        player_ids = data.get('player_ids', [])
        if not package_id or not player_ids:
            return JsonResponse({'error': 'Package and at least one player required.'}, status=400)
        items_input = [{'package_id': package_id, 'player_ids': player_ids}]

    if len(items_input) > 20:
        return JsonResponse({'error': 'Too many items in cart.'}, status=400)

    client, _ = Client.objects.get_or_create(user=request.user)
    s = _stripe()

    # Validate all packages and players upfront
    packages_map = {}
    all_line_items = []
    subtotal = Decimal('0')
    description_parts = []

    for item in items_input:
        pkg_id = item.get('package_id')
        p_ids = item.get('player_ids', [])
        if not pkg_id or not p_ids:
            return JsonResponse({'error': 'Each item needs package_id and player_ids.'}, status=400)

        if pkg_id not in packages_map:
            try:
                packages_map[pkg_id] = Package.objects.get(pk=pkg_id, is_active=True)
            except Package.DoesNotExist:
                return JsonResponse({'error': f'Package {pkg_id} not found.'}, status=404)

        package = packages_map[pkg_id]
        players = list(Player.objects.filter(pk__in=p_ids, client=client, is_active=True))
        if len(players) != len(p_ids):
            return JsonResponse({'error': 'One or more players not found.'}, status=400)

        # Sibling discount per package
        existing_active_player_ids = set(
            client.packages.filter(package=package, status='active').values_list('player_id', flat=True)
        )
        # Track which players in this batch already have a full-price entry for this package
        batch_full_price_exists = any(
            li['package_id'] == pkg_id and not li['sibling_discount'] for li in all_line_items
        )

        for player in players:
            price = package.price
            sibling = False
            has_existing = player.pk in existing_active_player_ids
            another_active = existing_active_player_ids - {player.pk}
            if has_existing or another_active or batch_full_price_exists:
                sibling = True
                price = (package.price * Decimal('50') / Decimal('100')).quantize(Decimal('0.01'))

            all_line_items.append({
                'package_id': pkg_id,
                'package_name': package.name,
                'player_id': player.pk,
                'player_name': f'{player.first_name} {player.last_name}',
                'price': str(price),
                'original_price': str(package.price),
                'sibling_discount': sibling,
            })
            subtotal += price
            batch_full_price_exists = batch_full_price_exists or not sibling

        description_parts.append(f'{package.name} x{len(players)}')

    if not all_line_items:
        return JsonResponse({'error': 'Cart is empty.'}, status=400)

    # Promo code (applied to subtotal after sibling discounts)
    # select_for_update prevents concurrent requests from double-redeeming the same code
    discount_code = None
    discount_amount = Decimal('0')
    if promo_code_str:
        try:
            with transaction.atomic():
                dc = DiscountCode.objects.select_for_update().get(code=promo_code_str, is_active=True)
                ok, _ = dc.is_valid_now()
                if ok and dc.scope in ('all', 'packages'):
                    # If code is restricted to specific packages, check overlap
                    if dc.specific_packages.exists():
                        cart_pkg_ids = set(packages_map.keys())
                        valid_pkg_ids = set(dc.specific_packages.values_list('pk', flat=True))
                        if not cart_pkg_ids & valid_pkg_ids:
                            dc = None
                    if dc and dc.min_purchase_amount and subtotal < dc.min_purchase_amount:
                        dc = None
                    if dc:
                        client_uses = dc.uses.filter(client=client, status='applied').count()
                        if client_uses < dc.max_uses_per_client:
                            discount_amount = dc.compute_discount(subtotal)
                            discount_code = dc
        except DiscountCode.DoesNotExist:
            pass

    # APC Select credit
    credit_applied = Decimal('0')
    if apply_credit:
        remaining = subtotal - discount_amount
        for credit in client.credits.filter(status='available').order_by('expires_at'):
            if credit.is_usable and remaining > 0:
                use_amount = min(credit.amount, remaining)
                credit_applied += use_amount
                remaining -= use_amount

    final_amount = max(subtotal - discount_amount - credit_applied, Decimal('0'))

    # Metadata for webhook — items grouped by package
    items_meta = json.dumps([
        {'package_id': li['package_id'], 'player_id': li['player_id'], 'price': li['price']}
        for li in all_line_items
    ])
    description = ', '.join(description_parts)

    # Free order — 100% discount applied, skip Stripe and activate immediately
    if final_amount == Decimal('0'):
        import uuid
        free_intent_id = f'FREE-{uuid.uuid4().hex}'
        with transaction.atomic():
            Payment.objects.create(
                client=client,
                amount=Decimal('0'),
                stripe_payment_intent_id=free_intent_id,
                description=f'Packages (free): {description}',
                status='succeeded',
            )
            if discount_code and discount_amount > 0:
                DiscountCodeUse.objects.create(
                    code=discount_code,
                    client=client,
                    discount_amount=discount_amount,
                    original_amount=subtotal,
                    final_amount=Decimal('0'),
                    status='pending',
                    stripe_payment_intent_id=free_intent_id,
                )
            _activate_multi_packages(
                client.pk, items_meta, free_intent_id,
                metadata={
                    'discount_code': promo_code_str or '',
                    'discount_amount': str(discount_amount),
                    'credit_applied': str(credit_applied),
                },
            )
        return JsonResponse({
            'free': True,
            'amount': '0.00',
            'original_amount': str(sum(Decimal(li['original_price']) for li in all_line_items)),
            'subtotal': str(subtotal),
            'discount_amount': str(discount_amount),
            'credit_applied': str(credit_applied),
            'line_items': all_line_items,
        })

    amount_cents = int(final_amount * 100)

    try:
        customer_id = _get_or_create_stripe_customer(client)
        intent = s.PaymentIntent.create(
            amount=amount_cents,
            currency='usd',
            customer=customer_id,
            metadata={
                'type': 'multi_package_purchase',
                'client_id': str(client.pk),
                'items': items_meta,
                'discount_code': promo_code_str or '',
                'discount_amount': str(discount_amount),
                'credit_applied': str(credit_applied),
            },
            description=f'Packages: {description}',
        )

        Payment.objects.create(
            client=client,
            amount=final_amount,
            stripe_payment_intent_id=intent.id,
            description=f'Packages: {description}',
            status='pending',
        )

        # Track discount use
        if discount_code and discount_amount > 0:
            DiscountCodeUse.objects.create(
                code=discount_code,
                client=client,
                discount_amount=discount_amount,
                original_amount=subtotal,
                final_amount=final_amount,
                status='pending',
                stripe_payment_intent_id=intent.id,
            )

        # Track sibling discount uses
        sibling_items = [li for li in all_line_items if li['sibling_discount']]
        if sibling_items:
            sibling_dc, _ = DiscountCode.objects.get_or_create(
                code='SIBLING-AUTO',
                defaults={
                    'description': 'Automatic sibling discount (50% off same package)',
                    'discount_type': 'percent',
                    'value': Decimal('50.00'),
                    'scope': 'all',
                    'max_uses': None,
                    'max_uses_per_client': 99,
                    'is_active': True,
                }
            )
            sibling_total = sum(
                Decimal(li['original_price']) - Decimal(li['price']) for li in sibling_items
            )
            original_total = sum(Decimal(li['original_price']) for li in all_line_items)
            DiscountCodeUse.objects.create(
                code=sibling_dc,
                client=client,
                discount_amount=sibling_total,
                original_amount=original_total,
                final_amount=final_amount,
                status='pending',
                stripe_payment_intent_id=intent.id,
            )

        return JsonResponse({
            'client_secret': intent.client_secret,
            'amount': str(final_amount),
            'original_amount': str(sum(Decimal(li['original_price']) for li in all_line_items)),
            'subtotal': str(subtotal),
            'discount_amount': str(discount_amount),
            'credit_applied': str(credit_applied),
            'line_items': all_line_items,
        })

    except stripe.error.StripeError as e:
        logger.exception('Multi-package PaymentIntent creation failed')
        return JsonResponse({'error': str(e.user_message)}, status=400)


# ── Recurring subscription ────────────────────────────────────────────────────

@login_required
@require_POST
def create_package_subscription(request, package_id):
    """Create a Stripe Subscription for a recurring package."""
    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({'error': 'Payments not yet configured.'}, status=503)

    package = get_object_or_404(Package, pk=package_id, is_active=True)
    if not package.stripe_price_id:
        return JsonResponse({'error': 'This package is not available for subscription.'}, status=400)

    client, _ = Client.objects.get_or_create(user=request.user)
    s = _stripe()

    try:
        customer_id = _get_or_create_stripe_customer(client)
        payment_method_id = request.POST.get('payment_method_id')

        if payment_method_id:
            s.PaymentMethod.attach(payment_method_id, customer=customer_id)
            s.Customer.modify(customer_id,
                invoice_settings={'default_payment_method': payment_method_id})

        subscription = s.Subscription.create(
            customer=customer_id,
            items=[{'price': package.stripe_price_id}],
            expand=['latest_invoice.payment_intent'],
            metadata={
                'client_id': str(client.pk),
                'package_id': str(package.pk),
                'subscription_id': '',  # placeholder — overwritten below after creation
            },
        )

        # Persist subscription_id in its own metadata so _activate_package can store it
        s.Subscription.modify(subscription.id, metadata={
            'client_id': str(client.pk),
            'package_id': str(package.pk),
            'subscription_id': subscription.id,
        })

        return JsonResponse({
            'subscription_id': subscription.id,
            'status': subscription.status,
            'client_secret': subscription.latest_invoice.payment_intent.client_secret
                             if subscription.latest_invoice and subscription.latest_invoice.payment_intent
                             else None,
        })

    except stripe.error.StripeError as e:
        logger.exception('Subscription creation failed for package %s', package_id)
        return JsonResponse({'error': str(e.user_message)}, status=400)


# ── Webhook ───────────────────────────────────────────────────────────────────

@csrf_exempt
def payments_webhook(request):
    """
    Stripe webhook endpoint — single source of truth for payment confirmation.
    Register at: https://dashboard.stripe.com/webhooks
    URL: https://atletasperformancecenter.com/payments/webhook/
    Events to subscribe: payment_intent.succeeded, payment_intent.payment_failed,
                         invoice.payment_succeeded, invoice.payment_failed, invoice.upcoming,
                         customer.subscription.deleted, charge.refunded
    """
    payload    = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error('STRIPE_WEBHOOK_SECRET not configured — rejecting webhook')
        return HttpResponse(status=400)
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            logger.warning('Webhook signature verification failed: %s', e)
            return HttpResponse(status=400)

    event_type = event.get('type', '')
    data       = event['data']['object']

    logger.info('Stripe webhook: %s', event_type)

    dispatch = {
        'payment_intent.succeeded':       _handle_payment_succeeded,
        'payment_intent.payment_failed':  _handle_payment_failed,
        'invoice.payment_succeeded':      _handle_subscription_renewed,
        'invoice.payment_failed':         _handle_subscription_payment_failed,
        'invoice.upcoming':               _handle_invoice_upcoming,
        'customer.subscription.deleted':  _handle_subscription_cancelled,
        'charge.refunded':                _handle_refund,
    }
    handler = dispatch.get(event_type)
    if handler:
        try:
            handler(data)
        except Exception:
            logger.exception('Webhook handler failed for %s', event_type)
            return HttpResponse(status=500)

    return HttpResponse(status=200)


def _handle_payment_succeeded(intent):
    """PaymentIntent succeeded → activate package or mark rental paid."""
    try:
        payment = Payment.objects.get(stripe_payment_intent_id=intent['id'])
        payment.status = 'succeeded'
        payment.stripe_charge_id = intent.get('latest_charge', '')
        payment.save()
    except Payment.DoesNotExist:
        # May be a booking drop-in payment — handled via metadata below
        logger.info('payment_intent.succeeded: no Payment record for %s (may be booking payment)', intent['id'])

    metadata     = intent.get('metadata', {})
    payment_type = metadata.get('type')

    if payment_type == 'package_purchase':
        _activate_package(
            client_id=metadata.get('client_id'),
            package_id=metadata.get('package_id'),
            payment_intent_id=intent['id'],
            metadata=metadata,
            subscription_id=metadata.get('subscription_id', ''),
        )

    elif payment_type == 'batch_package_purchase':
        _activate_batch_packages(
            client_id=metadata.get('client_id'),
            package_id=metadata.get('package_id'),
            players_json=metadata.get('players', '[]'),
            payment_intent_id=intent['id'],
            metadata=metadata,
        )

    elif payment_type == 'multi_package_purchase':
        _activate_multi_packages(
            client_id=metadata.get('client_id'),
            items_json=metadata.get('items', '[]'),
            payment_intent_id=intent['id'],
            metadata=metadata,
        )

    elif payment_type == 'facility_rental':
        _mark_rental_paid(
            slot_id=metadata.get('slot_id'),
            payment_intent_id=intent['id'],
        )

    elif metadata.get('type') == 'drop_in_booking':
        _create_paid_bookings(
            client_id=metadata.get('client_id'),
            items_json=metadata.get('items', '[]'),
            payment_intent_id=intent['id'],
            metadata=metadata,
        )

    elif metadata.get('booking_ids'):
        ids = metadata['booking_ids'].split(',')
        per_booking_amount = intent.get('amount', 0) // len(ids) if ids else 0
        for bid in ids:
            _confirm_booking_paid(
                booking_id=bid.strip(),
                payment_intent_id=intent['id'],
                amount=per_booking_amount,
            )

    elif metadata.get('booking_id'):
        _confirm_booking_paid(
            booking_id=metadata.get('booking_id'),
            payment_intent_id=intent['id'],
            amount=intent.get('amount', 0),
        )

    # Send payment receipt for all successful payments
    _send_payment_receipt(intent, metadata)


def _send_payment_receipt(intent, metadata):
    """Send a payment receipt email after any successful PaymentIntent."""
    import json
    from decimal import Decimal
    from django.template.loader import render_to_string
    from clients.models import Client
    from clients.services import NotificationService

    client_id = metadata.get('client_id')
    if not client_id:
        return

    try:
        client = Client.objects.select_related('user').get(pk=client_id)
    except Client.DoesNotExist:
        return

    amount_cents = intent.get('amount', 0)
    amount = Decimal(amount_cents) / 100
    description = intent.get('description', 'Payment')
    payment_intent_id = intent['id']
    charge_id = intent.get('latest_charge', '')

    # Try to get payment method details from Stripe
    payment_method_str = ''
    try:
        s = _stripe()
        if charge_id:
            charge = s.Charge.retrieve(charge_id)
            pm = charge.get('payment_method_details', {})
            card = pm.get('card', {})
            if card:
                brand = (card.get('brand') or '').capitalize()
                last4 = card.get('last4', '')
                payment_method_str = f'{brand} ending in {last4}' if brand else f'Card ending in {last4}'
    except Exception:
        pass

    # Build line items from metadata
    line_items = []
    discount_total = ''
    credit_applied = ''

    items_json = metadata.get('items') or metadata.get('players')
    if items_json:
        try:
            items_data = json.loads(items_json)
            for item in items_data:
                li = {'amount': f"{Decimal(item.get('price', '0')):.2f}"}
                if 'player_id' in item:
                    from clients.models import Player
                    try:
                        p = Player.objects.get(pk=item['player_id'])
                        li['player'] = f'{p.first_name} {p.last_name}'
                    except Player.DoesNotExist:
                        pass
                if 'package_id' in item:
                    try:
                        pkg = Package.objects.get(pk=item['package_id'])
                        li['name'] = pkg.name
                    except Package.DoesNotExist:
                        li['name'] = description
                else:
                    pkg_id = metadata.get('package_id')
                    if pkg_id:
                        try:
                            li['name'] = Package.objects.get(pk=pkg_id).name
                        except Package.DoesNotExist:
                            li['name'] = description
                    else:
                        li['name'] = description
                line_items.append(li)
        except (json.JSONDecodeError, TypeError):
            pass

    if metadata.get('discount_amount'):
        try:
            da = Decimal(metadata['discount_amount'])
            if da > 0:
                discount_total = f'{da:.2f}'
        except Exception:
            pass

    if metadata.get('credit_applied'):
        try:
            ca = Decimal(metadata['credit_applied'])
            if ca > 0:
                credit_applied = f'{ca:.2f}'
        except Exception:
            pass

    site_url = getattr(settings, 'SITE_URL', 'https://atletasperformancecenter.com')
    ctx = {
        'amount_paid': f'{amount:.2f}',
        'description': description,
        'payment_date': timezone.localtime().strftime('%B %-d, %Y at %-I:%M %p'),
        'payment_method': payment_method_str,
        'transaction_id': payment_intent_id,
        'line_items': line_items,
        'discount_total': discount_total,
        'credit_applied': credit_applied,
        'packages_url': f'{site_url}/portal/packages/',
        'client_name': client.user.first_name or client.user.username,
        'site_url': site_url,
        'current_year': timezone.now().year,
    }

    try:
        html_content = render_to_string('emails/payment_receipt.html', ctx)
        text_content = (
            f"Payment Receipt\n\n"
            f"Amount: ${amount:.2f}\n"
            f"Description: {description}\n"
            f"Date: {ctx['payment_date']}\n"
            f"Transaction: {payment_intent_id}\n\n"
            f"View your packages: {site_url}/portal/packages/"
        )
        NotificationService.send_email(
            to_email=client.user.email,
            subject=f'🧾 Payment Receipt — ${amount:.2f}',
            html_content=html_content,
            text_content=text_content,
            context=ctx,
        )
        logger.info('Payment receipt sent to %s for %s', client.user.email, payment_intent_id)
    except Exception:
        logger.exception('Failed to send payment receipt for %s', payment_intent_id)


def _activate_package(client_id, package_id, payment_intent_id, metadata=None, subscription_id=''):
    """Create an active ClientPackage after successful payment."""
    from datetime import timedelta
    from decimal import Decimal
    try:
        client  = Client.objects.get(pk=client_id)
        package = Package.objects.get(pk=package_id)
    except (Client.DoesNotExist, Package.DoesNotExist):
        logger.error('activate_package: client %s or package %s not found', client_id, package_id)
        return

    # Extract subscription_id from metadata if not passed directly
    if not subscription_id and metadata:
        subscription_id = metadata.get('subscription_id', '')

    cp = ClientPackage.objects.create(
        client=client,
        package=package,
        status='active',
        start_date=timezone.localdate(),
        expiry_date=package.event_end_date if package.event_end_date else timezone.localdate() + timedelta(weeks=package.validity_weeks),
        sessions_remaining=package.sessions_included,
        stripe_payment_id=payment_intent_id,
        stripe_subscription_id=subscription_id or '',
    )
    logger.info('ClientPackage #%s activated for %s — %s', cp.pk, client, package.name)
    # Queue package activation email (45-second window)
    try:
        from clients.notification_utils import queue_grouped_notification
        queue_grouped_notification(
            client=client,
            event_type='package_activated',
            context={
                'package_id': cp.id,
                'package_name': package.name,
                'price': float(package.price),
            },
            group_key=f'pkg_{cp.id}',
            window_seconds=45,
        )
    except Exception:
        logger.exception('_activate_package: notification queuing failed for package %s', cp.pk)

    # Finalize pending DiscountCodeUse for this PaymentIntent
    from clients.models import DiscountCodeUse
    DiscountCodeUse.objects.filter(
        stripe_payment_intent_id=payment_intent_id, status='pending'
    ).update(status='applied', applied_to_package=cp)

    # Finalize APC Select credits that were applied during checkout
    if metadata:
        credit_applied_str = metadata.get('credit_applied', '0')
        try:
            remaining = Decimal(credit_applied_str)
        except Exception:
            remaining = Decimal('0')
        if remaining > 0:
            from clients.models import ClientCredit
            for credit in client.credits.filter(status='available').order_by('expires_at'):
                if credit.is_usable and remaining > 0:
                    use_amount = min(credit.amount, remaining)
                    credit.status = 'applied'
                    credit.applied_to = cp
                    credit.applied_at = timezone.now()
                    credit.save(update_fields=['status', 'applied_to', 'applied_at'])
                    remaining -= use_amount

    # APC Select: auto-grant 6×$40 monthly credits (staggered, one per month)
    if package.package_type == 'select':
        from clients.models import ClientCredit
        from datetime import date
        year_end = date(timezone.localdate().year, 12, 31)
        for month in range(1, 7):
            ClientCredit.objects.create(
                client=client,
                amount=Decimal('40.00'),
                credit_type='select_monthly',
                source_package=cp,
                expires_at=year_end,
                notes=f'APC Select — Month {month} training credit ($40 toward any APC Training session or package)',
            )
        logger.info('APC Select: 6 monthly credits created for %s', client)

    # Referral activation: check if this is the referred user's first purchase
    try:
        from clients.services import ReferralService
        ReferralService.check_and_activate(client, package.price)
    except Exception:
        logger.exception('_activate_package: referral activation failed for client %s', client.pk)


def _activate_batch_packages(client_id, package_id, players_json, payment_intent_id, metadata=None):
    """Create multiple ClientPackages (one per player) after successful batch payment."""
    import json
    from datetime import timedelta
    from decimal import Decimal
    from clients.models import Player, DiscountCodeUse

    try:
        client = Client.objects.get(pk=client_id)
        package = Package.objects.get(pk=package_id)
        players_data = json.loads(players_json)
    except (Client.DoesNotExist, Package.DoesNotExist, json.JSONDecodeError) as e:
        logger.error('_activate_batch_packages: invalid data — %s', e)
        return

    expiry = package.event_end_date if package.event_end_date else timezone.localdate() + timedelta(weeks=package.validity_weeks)
    created_packages = []

    for item in players_data:
        try:
            player = Player.objects.get(pk=item['player_id'], client=client)
        except Player.DoesNotExist:
            logger.error('_activate_batch_packages: player %s not found', item.get('player_id'))
            continue

        cp = ClientPackage.objects.create(
            client=client,
            package=package,
            player=player,
            status='active',
            start_date=timezone.localdate(),
            expiry_date=expiry,
            sessions_remaining=package.sessions_included,
            stripe_payment_id=payment_intent_id,
        )
        created_packages.append(cp)
        logger.info('Batch: ClientPackage #%s activated for %s (%s)', cp.pk, player, package.name)

        try:
            from clients.notification_utils import queue_grouped_notification
            queue_grouped_notification(
                client=client,
                event_type='package_activated',
                context={
                    'package_id': cp.id,
                    'package_name': package.name,
                    'player_name': f'{player.first_name} {player.last_name}',
                    'price': float(item.get('price', package.price)),
                },
                group_key=f'pkg_{cp.id}',
                window_seconds=45,
            )
        except Exception:
            pass

    # Finalize discount code uses
    if created_packages:
        DiscountCodeUse.objects.filter(
            stripe_payment_intent_id=payment_intent_id, status='pending'
        ).update(status='applied', applied_to_package=created_packages[0])

    # Finalize APC Select credits
    if metadata and created_packages:
        credit_applied_str = metadata.get('credit_applied', '0')
        try:
            remaining = Decimal(credit_applied_str)
        except Exception:
            remaining = Decimal('0')
        if remaining > 0:
            from clients.models import ClientCredit
            for credit in client.credits.filter(status='available').order_by('expires_at'):
                if credit.is_usable and remaining > 0:
                    use_amount = min(credit.amount, remaining)
                    credit.status = 'applied'
                    credit.applied_to = created_packages[0]
                    credit.applied_at = timezone.now()
                    credit.save(update_fields=['status', 'applied_to', 'applied_at'])
                    remaining -= use_amount

    # Referral activation (uses total purchase amount)
    if created_packages:
        total_paid = sum(Decimal(item.get('price', str(package.price))) for item in players_data)
        try:
            from clients.services import ReferralService
            ReferralService.check_and_activate(client, total_paid)
        except Exception:
            logger.exception('_activate_batch_packages: referral activation failed for client %s', client.pk)


def _activate_multi_packages(client_id, items_json, payment_intent_id, metadata=None):
    """Create ClientPackages for a multi-package cart after successful payment."""
    import json
    from datetime import timedelta
    from decimal import Decimal
    from clients.models import Player, DiscountCodeUse

    try:
        client = Client.objects.get(pk=client_id)
        items_data = json.loads(items_json)
    except (Client.DoesNotExist, json.JSONDecodeError) as e:
        logger.error('_activate_multi_packages: invalid data — %s', e)
        return

    created_packages = []
    packages_cache = {}

    for item in items_data:
        pkg_id = item.get('package_id')
        player_id = item.get('player_id')

        if pkg_id not in packages_cache:
            try:
                packages_cache[pkg_id] = Package.objects.get(pk=pkg_id)
            except Package.DoesNotExist:
                logger.error('_activate_multi_packages: package %s not found', pkg_id)
                continue

        package = packages_cache[pkg_id]

        try:
            player = Player.objects.get(pk=player_id, client=client)
        except Player.DoesNotExist:
            logger.error('_activate_multi_packages: player %s not found', player_id)
            continue

        expiry = package.event_end_date if package.event_end_date else timezone.localdate() + timedelta(weeks=package.validity_weeks)

        cp = ClientPackage.objects.create(
            client=client,
            package=package,
            player=player,
            status='active',
            start_date=timezone.localdate(),
            expiry_date=expiry,
            sessions_remaining=package.sessions_included,
            stripe_payment_id=payment_intent_id,
        )
        created_packages.append(cp)
        logger.info('Multi: ClientPackage #%s activated for %s (%s)', cp.pk, player, package.name)

        try:
            from clients.notification_utils import queue_grouped_notification
            queue_grouped_notification(
                client=client,
                event_type='package_activated',
                context={
                    'package_id': cp.id,
                    'package_name': package.name,
                    'player_name': f'{player.first_name} {player.last_name}',
                    'price': float(item.get('price', package.price)),
                },
                group_key=f'pkg_{cp.id}',
                window_seconds=45,
            )
        except Exception:
            pass

    # Finalize discount code uses
    if created_packages:
        DiscountCodeUse.objects.filter(
            stripe_payment_intent_id=payment_intent_id, status='pending'
        ).update(status='applied', applied_to_package=created_packages[0])

    # Finalize APC Select credits
    if metadata and created_packages:
        credit_applied_str = metadata.get('credit_applied', '0')
        try:
            remaining = Decimal(credit_applied_str)
        except Exception:
            remaining = Decimal('0')
        if remaining > 0:
            from clients.models import ClientCredit
            for credit in client.credits.filter(status='available').order_by('expires_at'):
                if credit.is_usable and remaining > 0:
                    use_amount = min(credit.amount, remaining)
                    credit.status = 'applied'
                    credit.applied_to = created_packages[0]
                    credit.applied_at = timezone.now()
                    credit.save(update_fields=['status', 'applied_to', 'applied_at'])
                    remaining -= use_amount

    # Referral activation
    if created_packages:
        total_paid = sum(Decimal(item.get('price', '0')) for item in items_data)
        try:
            from clients.services import ReferralService
            ReferralService.check_and_activate(client, total_paid)
        except Exception:
            logger.exception('_activate_multi_packages: referral activation failed for client %s', client.pk)


def _mark_rental_paid(slot_id, payment_intent_id):
    """Mark a FieldRentalSlot as paid after successful payment."""
    try:
        from clients.models import FieldRentalSlot
        slot = FieldRentalSlot.objects.get(pk=slot_id)
        slot.status = 'booked'
        slot.save(update_fields=['status'])
        logger.info('FieldRentalSlot #%s marked paid', slot_id)
    except Exception:
        logger.exception('mark_rental_paid failed for slot %s', slot_id)


def _handle_payment_failed(intent):
    """PaymentIntent failed → update Payment record."""
    try:
        payment = Payment.objects.get(stripe_payment_intent_id=intent['id'])
        payment.status = 'failed'
        payment.save(update_fields=['status'])
    except Payment.DoesNotExist:
        pass


_BILLING_TIER_WEEKS = {
    'monthly': 4,
    'thirds':  16,
    'half':    12,
    'full':    52,
}


def _handle_subscription_renewed(invoice):
    """Subscription billing cycle succeeded → extend ClientPackage expiry and notify member."""
    from datetime import timedelta
    subscription_id = invoice.get('subscription')
    if not subscription_id:
        return
    cp = ClientPackage.objects.filter(
        stripe_subscription_id=subscription_id, status='active'
    ).select_related('package', 'client').first()
    if not cp:
        return

    weeks = _BILLING_TIER_WEEKS.get(cp.package.billing_tier, 4)
    cp.expiry_date = timezone.localdate() + timedelta(weeks=weeks)
    cp.save(update_fields=['expiry_date'])
    logger.info('Subscription renewed: ClientPackage #%s extended to %s (%s weeks)', cp.pk, cp.expiry_date, weeks)

    # Notify the member
    try:
        from clients.models import Notification
        Notification.objects.create(
            client=cp.client,
            notification_type='promotional',
            title='APC Select Membership Renewed',
            message=(
                f'Your APC Select membership has been renewed. '
                f'Access continues through {cp.expiry_date.strftime("%B %-d, %Y")}.'
            ),
            method='in_app',
        )
    except Exception:
        logger.exception('_handle_subscription_renewed: notification failed for cp %s', cp.pk)


def _handle_subscription_payment_failed(invoice):
    """Subscription payment failed → notify member to update their card."""
    subscription_id = invoice.get('subscription')
    if not subscription_id:
        return
    # Only notify on the first failure attempt (attempt_count == 1) to avoid spam
    if invoice.get('attempt_count', 1) != 1:
        return
    cp = ClientPackage.objects.filter(
        stripe_subscription_id=subscription_id, status='active'
    ).select_related('client').first()
    if not cp:
        return
    try:
        from clients.models import Notification
        from django.conf import settings as _s
        site_url = getattr(_s, 'SITE_URL', 'https://atletasperformancecenter.com')
        Notification.objects.create(
            client=cp.client,
            notification_type='promotional',
            title='APC Select — Payment Failed',
            message=(
                f'Your APC Select membership payment could not be processed. '
                f'Please update your payment method at {site_url}/portal/packages/ '
                f'to keep your membership active. Stripe will retry automatically.'
            ),
            method='in_app',
        )
    except Exception:
        logger.exception('_handle_subscription_payment_failed: notification failed for cp %s', cp.pk)


def _handle_invoice_upcoming(invoice):
    """Upcoming invoice (7 days before renewal) → remind member of upcoming charge."""
    subscription_id = invoice.get('subscription')
    if not subscription_id:
        return
    cp = ClientPackage.objects.filter(
        stripe_subscription_id=subscription_id, status='active'
    ).select_related('package', 'client').first()
    if not cp:
        return
    try:
        from clients.models import Notification
        from decimal import Decimal
        amount_cents = invoice.get('amount_due', 0)
        amount = Decimal(amount_cents) / 100
        period_end_ts = invoice.get('period_end')
        if period_end_ts:
            import datetime
            renewal_date = datetime.datetime.utcfromtimestamp(period_end_ts).strftime('%B %-d, %Y')
        else:
            renewal_date = 'soon'
        Notification.objects.create(
            client=cp.client,
            notification_type='promotional',
            title='APC Select Renewing Soon',
            message=(
                f'Your APC Select membership will automatically renew on {renewal_date} '
                f'for ${amount:.2f}. No action needed — your card on file will be charged.'
            ),
            method='in_app',
        )
    except Exception:
        logger.exception('_handle_invoice_upcoming: notification failed for cp %s', cp.pk)


def _handle_subscription_cancelled(subscription):
    """Subscription cancelled/deleted → expire ClientPackage and notify member."""
    updated = ClientPackage.objects.filter(
        stripe_subscription_id=subscription['id']
    ).update(status='expired')
    logger.info('Subscription cancelled: %s ClientPackage(s) expired', updated)

    # Notify the member
    try:
        cp = ClientPackage.objects.filter(
            stripe_subscription_id=subscription['id']
        ).select_related('client').first()
        if cp:
            from clients.models import Notification
            cancel_at = subscription.get('cancel_at') or subscription.get('canceled_at')
            if cancel_at:
                import datetime
                end_date = datetime.datetime.utcfromtimestamp(cancel_at).strftime('%B %-d, %Y')
                msg = f'Your APC Select membership has been cancelled. Access ends on {end_date}.'
            else:
                msg = 'Your APC Select membership has been cancelled.'
            Notification.objects.create(
                client=cp.client,
                notification_type='promotional',
                title='APC Select Membership Cancelled',
                message=msg,
                method='in_app',
            )
    except Exception:
        logger.exception('_handle_subscription_cancelled: notification failed')


def _handle_refund(charge):
    """Charge refunded → mark Payment as refunded."""
    try:
        payment = Payment.objects.get(stripe_charge_id=charge['id'])
        payment.status = 'refunded'
        payment.save(update_fields=['status'])
        logger.info('Payment #%s marked refunded', payment.pk)
    except Payment.DoesNotExist:
        pass


# ── Booking drop-in payment ───────────────────────────────────────────────────

@login_required
@require_POST
def create_booking_payment_intent(request, booking_id):
    """Create a Stripe PaymentIntent for a pending drop-in booking."""
    from bookings.models import Booking
    from decimal import Decimal

    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({'error': 'Stripe is not configured.'}, status=400)

    client = get_object_or_404(Client, user=request.user)
    booking = get_object_or_404(Booking, pk=booking_id, client=client, payment_status='pending')

    # Amount is stored on the booking; fall back to session drop-in price
    amount = booking.amount_paid  # may be 0 if not yet set
    if not amount and booking.session_type:
        amount = booking.session_type.get_drop_in_price()
    if not amount:
        return JsonResponse({'error': 'Cannot determine payment amount.'}, status=400)

    s = _stripe()
    customer_id = _get_or_create_stripe_customer(client)

    try:
        pi = s.PaymentIntent.create(
            amount=int(amount * 100),
            currency='usd',
            customer=customer_id,
            metadata={
                'booking_id': booking.pk,
                'client_id': client.pk,
                'session_type': booking.session_type.name if booking.session_type else '',
            },
            description=f"Drop-in booking #{booking.pk} — {booking.session_type.name if booking.session_type else 'Session'}",
        )
        # Record stripe intent on booking
        booking.amount_paid = amount
        booking.save(update_fields=['amount_paid'])

        return JsonResponse({
            'client_secret': pi.client_secret,
            'amount': str(amount),
        })
    except stripe.error.StripeError as e:
        logger.error('Booking payment intent error: %s', e)
        return JsonResponse({'error': e.user_message or 'Payment error. Please try again.'}, status=400)


@login_required
@require_POST
def create_batch_booking_payment_intent(request):
    """Create a Stripe PaymentIntent for drop-in sessions (no booking created yet).

    Accepts block_id/player_id pairs, validates availability, calculates total,
    and stores the items in metadata so the webhook can create bookings on payment success.
    """
    import json
    from coaches.models import ScheduleBlock
    from clients.models import Player
    from decimal import Decimal

    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({'error': 'Stripe is not configured.'}, status=400)

    client = get_object_or_404(Client, user=request.user)

    data = json.loads(request.body)
    items = data.get('items', [])
    promo_code_str = data.get('promo_code', '').strip().upper()
    apply_credit = data.get('apply_credit', False)
    if not items:
        return JsonResponse({'error': 'No items provided.'}, status=400)

    total = Decimal('0')
    descriptions = []
    validated = []

    for item in items:
        block_id = item.get('block_id')
        player_id = item.get('player_id')
        try:
            block = ScheduleBlock.objects.select_related('coach').prefetch_related('catalog_session_types').get(id=block_id)
            player = Player.objects.get(id=player_id, client=client)
        except (ScheduleBlock.DoesNotExist, Player.DoesNotExist):
            return JsonResponse({'error': 'Invalid session or player.'}, status=400)

        if not block.is_available:
            return JsonResponse({'error': f'Session at {block.date} {block.start_time} is no longer available.'}, status=400)

        catalog_types = list(block.catalog_session_types.all())
        session_type = catalog_types[0] if catalog_types else None
        if not session_type:
            return JsonResponse({'error': 'Session has no type configured.'}, status=400)

        price = block.price_override if block.price_override is not None else session_type.get_drop_in_price()
        if not price:
            return JsonResponse({'error': f'Cannot determine price for {session_type.name}.'}, status=400)

        total += price
        descriptions.append(f"{session_type.name} ({player.first_name} {player.last_name})")
        validated.append({'block_id': block_id, 'player_id': player_id, 'amount': str(price)})

    if total <= 0:
        return JsonResponse({'error': 'Cannot determine payment amount.'}, status=400)

    # Apply promo code discount (atomic check, sessions scope)
    from clients.models import DiscountCode, DiscountCodeUse
    discount_code = None
    discount_amount = Decimal('0.00')
    if promo_code_str:
        try:
            with transaction.atomic():
                dc = DiscountCode.objects.select_for_update().get(code=promo_code_str, is_active=True)
                valid, err = dc.is_valid_now()
                if not valid:
                    return JsonResponse({'error': err}, status=400)
                if dc.scope == 'packages':
                    return JsonResponse({'error': 'This code is only valid for package purchases.'}, status=400)
                already_used = DiscountCodeUse.objects.filter(
                    code=dc, client=client, status='applied'
                ).count()
                if already_used >= dc.max_uses_per_client:
                    return JsonResponse({'error': 'You have already used this code.'}, status=400)
                discount_amount = dc.compute_discount(total)
                discount_code = dc
        except DiscountCode.DoesNotExist:
            return JsonResponse({'error': 'Invalid promo code.'}, status=400)

    # APC Select credit
    credit_applied = Decimal('0.00')
    if apply_credit:
        remaining = total - discount_amount
        for credit in client.credits.filter(status='available').order_by('expires_at'):
            if credit.is_usable and remaining > 0:
                use_amount = min(credit.amount, remaining)
                credit_applied += use_amount
                remaining -= use_amount

    final_amount = max(total - discount_amount - credit_applied, Decimal('0.00'))

    # Free order — full credit/discount cover, skip Stripe entirely
    if final_amount == Decimal('0.00'):
        import uuid
        free_intent_id = f'FREE-{uuid.uuid4().hex}'
        with transaction.atomic():
            Payment.objects.create(
                client=client,
                amount=Decimal('0.00'),
                stripe_payment_intent_id=free_intent_id,
                description=f"Drop-in (free): {'; '.join(descriptions)}",
                status='succeeded',
            )
            if discount_code and discount_amount > 0:
                DiscountCodeUse.objects.create(
                    code=discount_code,
                    client=client,
                    discount_amount=discount_amount,
                    original_amount=total,
                    final_amount=Decimal('0.00'),
                    status='pending',
                    stripe_payment_intent_id=free_intent_id,
                )
            _create_paid_bookings(
                client_id=client.pk,
                items_json=json.dumps(validated),
                payment_intent_id=free_intent_id,
                metadata={
                    'credit_applied': str(credit_applied),
                    'discount_amount': str(discount_amount),
                },
            )
        return JsonResponse({
            'free': True,
            'amount': '0.00',
            'original_amount': str(total),
            'discount_amount': str(discount_amount),
            'credit_applied': str(credit_applied),
        })

    s = _stripe()
    customer_id = _get_or_create_stripe_customer(client)

    # Store items as JSON in metadata so webhook can create bookings
    items_json = json.dumps(validated)

    try:
        pi = s.PaymentIntent.create(
            amount=int(final_amount * 100),
            currency='usd',
            customer=customer_id,
            metadata={
                'type': 'drop_in_booking',
                'client_id': client.pk,
                'items': items_json,
                'promo_code': promo_code_str,
                'discount_amount': str(discount_amount),
                'original_amount': str(total),
                'credit_applied': str(credit_applied),
            },
            description=f"Drop-in: {'; '.join(descriptions)}",
        )

        # Record pending discount use so it can be finalised by webhook
        if discount_code and discount_amount > 0:
            DiscountCodeUse.objects.create(
                code=discount_code,
                client=client,
                discount_amount=discount_amount,
                original_amount=total,
                final_amount=final_amount,
                status='pending',
                stripe_payment_intent_id=pi.id,
            )

        return JsonResponse({
            'client_secret': pi.client_secret,
            'amount': str(final_amount),
            'credit_applied': str(credit_applied),
        })
    except stripe.error.StripeError as e:
        logger.error('Batch booking payment intent error: %s', e)
        return JsonResponse({'error': e.user_message or 'Payment error. Please try again.'}, status=400)


def _confirm_booking_paid(booking_id, payment_intent_id, amount):
    """Confirm a drop-in booking after successful Stripe payment."""
    from bookings.models import Booking
    from decimal import Decimal
    try:
        booking = Booking.objects.get(pk=booking_id, payment_status='pending')
        booking.payment_status = 'paid'
        booking.amount_paid = Decimal(amount) / 100
        booking.save(update_fields=['payment_status', 'amount_paid'])
        booking.confirm()
        logger.info('Booking #%s confirmed after payment %s', booking_id, payment_intent_id)
        # Finalize any pending discount code use for this booking
        from clients.models import DiscountCodeUse
        DiscountCodeUse.objects.filter(
            applied_to_booking=booking, status='pending'
        ).update(status='applied')
        # Queue confirmation email — appends to the 2-min reservation window if still open,
        # otherwise creates a new group (late payment) → separate "payment received" email
        try:
            from clients.notification_utils import queue_grouped_notification
            queue_grouped_notification(
                client=booking.client,
                event_type='booking_confirmed_paid',
                context={
                    'booking_id': booking.id,
                    'amount': float(booking.amount_paid),
                },
                group_key=f'booking_{booking.id}',
                window_seconds=45,
            )
        except Exception:
            logger.exception('_confirm_booking_paid: notification queuing failed for booking %s', booking_id)
    except Booking.DoesNotExist:
        logger.warning('_confirm_booking_paid: booking %s not found or already paid', booking_id)


def _create_paid_bookings(client_id, items_json, payment_intent_id, metadata=None):
    """Create confirmed bookings after successful drop-in payment (no pending state)."""
    import json
    from decimal import Decimal
    from bookings.models import Booking
    from coaches.models import ScheduleBlock
    from clients.models import Client, Player, DiscountCodeUse

    try:
        items = json.loads(items_json)
        client = Client.objects.get(pk=client_id)
    except (json.JSONDecodeError, Client.DoesNotExist) as e:
        logger.error('_create_paid_bookings: invalid data — %s', e)
        return

    created_bookings = []
    for item in items:
        try:
            block = ScheduleBlock.objects.select_related('coach').prefetch_related('catalog_session_types').get(id=item['block_id'])
            player = Player.objects.get(id=item['player_id'], client=client)
            catalog_types = list(block.catalog_session_types.all())
            session_type = catalog_types[0] if catalog_types else None

            booking = Booking.objects.create(
                client=client,
                player=player,
                coach=block.coach,
                session_type=session_type,
                scheduled_date=block.date,
                scheduled_time=block.start_time,
                client_package=None,
                status='confirmed',
                payment_status='paid',
                amount_paid=Decimal(item.get('amount', '0')),
            )
            created_bookings.append(booking)

            # Update block availability
            block.current_participants += 1
            if block.current_participants >= block.max_participants:
                block.status = 'booked'
            block.save()

            logger.info('Drop-in booking #%s created after payment %s', booking.id, payment_intent_id)

            try:
                from clients.notification_utils import queue_grouped_notification
                queue_grouped_notification(
                    client=client,
                    event_type='booking_confirmed_paid',
                    context={'booking_id': booking.id, 'amount': float(booking.amount_paid)},
                    group_key=f'booking_{booking.id}',
                    window_seconds=45,
                )
            except Exception:
                pass

        except Exception as e:
            logger.exception('_create_paid_bookings: failed to create booking for item %s — %s', item, e)

    # Finalise pending discount code use if one was applied
    try:
        DiscountCodeUse.objects.filter(
            stripe_payment_intent_id=payment_intent_id,
            status='pending',
        ).update(
            status='applied',
            applied_to_booking=created_bookings[0] if created_bookings else None,
        )
    except Exception as e:
        logger.warning('_create_paid_bookings: could not finalise discount use for %s — %s', payment_intent_id, e)

    # Finalise APC Select credits that were applied during checkout
    if metadata:
        credit_applied_str = metadata.get('credit_applied', '0')
        try:
            remaining = Decimal(credit_applied_str)
        except Exception:
            remaining = Decimal('0')
        if remaining > 0:
            from clients.models import ClientCredit
            for credit in client.credits.filter(status='available').order_by('expires_at'):
                if credit.is_usable and remaining > 0:
                    use_amount = min(credit.amount, remaining)
                    credit.status = 'applied'
                    credit.applied_at = timezone.now()
                    credit.save(update_fields=['status', 'applied_at'])
                    remaining -= use_amount
