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
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404

from clients.models import Client, Package, ClientPackage
from payments.models import Payment

logger = logging.getLogger(__name__)


def _stripe():
    """Return stripe module configured with secret key."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def _get_or_create_stripe_customer(client):
    """Get existing or create new Stripe customer for this client."""
    s = _stripe()
    if client.stripe_customer_id:
        return client.stripe_customer_id
    customer = s.Customer.create(
        email=client.user.email,
        name=client.user.get_full_name() or client.user.username,
        metadata={'client_id': client.pk},
    )
    client.stripe_customer_id = customer.id
    client.save(update_fields=['stripe_customer_id'])
    return customer.id


# ── One-time package purchase ─────────────────────────────────────────────────

@login_required
@require_POST
def create_package_payment_intent(request, package_id):
    """Create a Stripe PaymentIntent for a one-time package purchase."""
    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({'error': 'Payments not yet configured.'}, status=503)

    package = get_object_or_404(Package, pk=package_id, is_active=True)
    client, _ = Client.objects.get_or_create(user=request.user)
    s = _stripe()

    try:
        customer_id = _get_or_create_stripe_customer(client)
        intent = s.PaymentIntent.create(
            amount=int(package.price * 100),  # cents
            currency='usd',
            customer=customer_id,
            metadata={
                'type': 'package_purchase',
                'package_id': str(package.pk),
                'client_id': str(client.pk),
            },
            description=f'Package: {package.name}',
        )

        # Pending Payment record — confirmed by webhook
        Payment.objects.create(
            client=client,
            amount=package.price,
            stripe_payment_intent_id=intent.id,
            description=f'Package: {package.name}',
            status='pending',
        )

        return JsonResponse({
            'client_secret': intent.client_secret,
            'amount': str(package.price),
            'package_name': package.name,
        })

    except stripe.error.StripeError as e:
        logger.exception('PaymentIntent creation failed for package %s', package_id)
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
            metadata={'client_id': str(client.pk), 'package_id': str(package.pk)},
        )

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
                         invoice.payment_succeeded, customer.subscription.deleted, charge.refunded
    """
    payload    = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    if not settings.STRIPE_WEBHOOK_SECRET:
        # Dev mode: accept without signature verification
        import json
        try:
            event = json.loads(payload)
        except Exception:
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
        )

    elif payment_type == 'facility_rental':
        _mark_rental_paid(
            slot_id=metadata.get('slot_id'),
            payment_intent_id=intent['id'],
        )

    elif metadata.get('booking_id'):
        _confirm_booking_paid(
            booking_id=metadata.get('booking_id'),
            payment_intent_id=intent['id'],
            amount=intent.get('amount', 0),
        )


def _activate_package(client_id, package_id, payment_intent_id):
    """Create an active ClientPackage after successful payment."""
    from datetime import date, timedelta
    try:
        client  = Client.objects.get(pk=client_id)
        package = Package.objects.get(pk=package_id)
    except (Client.DoesNotExist, Package.DoesNotExist):
        logger.error('activate_package: client %s or package %s not found', client_id, package_id)
        return

    cp = ClientPackage.objects.create(
        client=client,
        package=package,
        status='active',
        start_date=date.today(),
        expiry_date=date.today() + timedelta(weeks=package.validity_weeks),
        sessions_remaining=package.sessions_included,
        stripe_payment_id=payment_intent_id,
    )
    logger.info('ClientPackage #%s activated for %s — %s', cp.pk, client, package.name)

    # APC Select: auto-grant 6×$40 monthly credits (staggered, one per month)
    if package.package_type == 'select':
        from clients.models import ClientCredit
        from decimal import Decimal
        for month in range(1, 7):
            credit_date = date.today() + timedelta(weeks=4 * month)
            ClientCredit.objects.create(
                client=client,
                amount=Decimal('40.00'),
                credit_type='select_monthly',
                source_package=cp,
                expires_at=credit_date + timedelta(weeks=4),
                notes=f'APC Select — Month {month} training credit ($40 toward any APC Training package)',
            )
        logger.info('APC Select: 6 monthly credits created for %s', client)


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


def _handle_subscription_renewed(invoice):
    """Monthly subscription renewed → extend ClientPackage expiry."""
    from datetime import date, timedelta
    subscription_id = invoice.get('subscription')
    if not subscription_id:
        return
    cp = ClientPackage.objects.filter(
        stripe_subscription_id=subscription_id, status='active'
    ).first()
    if cp:
        cp.expiry_date = date.today() + timedelta(weeks=4)
        cp.save(update_fields=['expiry_date'])
        logger.info('Subscription renewed: ClientPackage #%s extended to %s', cp.pk, cp.expiry_date)


def _handle_subscription_cancelled(subscription):
    """Subscription cancelled/deleted → expire ClientPackage."""
    updated = ClientPackage.objects.filter(
        stripe_subscription_id=subscription['id']
    ).update(status='expired')
    logger.info('Subscription cancelled: %s ClientPackage(s) expired', updated)


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
        return JsonResponse({'error': str(e)}, status=400)


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
    except Booking.DoesNotExist:
        logger.warning('_confirm_booking_paid: booking %s not found or already paid', booking_id)
