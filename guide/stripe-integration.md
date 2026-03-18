# Stripe Integration Guide
**Scope:** One-time package purchase · Facility rental payment · Recurring subscriptions · Refunds

---

## Overview

The `payments` app already has a `Payment` model with `stripe_payment_intent_id`, `stripe_charge_id`, and `status` fields. Settings already read `STRIPE_PUBLIC_KEY`, `STRIPE_SECRET_KEY`, and `STRIPE_WEBHOOK_SECRET` from `.env`.

This guide covers building out the actual Stripe API calls for each flow.

---

## 1. Install & Configure

```bash
pip install stripe
# Add to requirements.txt
echo "stripe" >> requirements.txt
```

Stripe keys are already wired in `settings.py`:
```python
STRIPE_PUBLIC_KEY = env('STRIPE_PUBLIC_KEY', default='')
STRIPE_SECRET_KEY = env('STRIPE_SECRET_KEY', default='')
STRIPE_WEBHOOK_SECRET = env('STRIPE_WEBHOOK_SECRET', default='')
```

Add a helper at the top of any view or service file that calls Stripe:
```python
import stripe
from django.conf import settings
stripe.api_key = settings.STRIPE_SECRET_KEY
```

---

## 2. Flow 1 — One-Time Package Purchase

**Trigger:** Client selects a `Package` and clicks "Buy"
**Stripe object:** `PaymentIntent`

### Backend view

```python
# clients/views.py (or payments/views.py)
import stripe
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import ClientPackage, Package
from payments.models import Payment

stripe.api_key = settings.STRIPE_SECRET_KEY

@login_required
@require_POST
def create_package_payment_intent(request, package_id):
    package = get_object_or_404(Package, pk=package_id, is_active=True)
    client, _ = Client.objects.get_or_create(user=request.user)

    intent = stripe.PaymentIntent.create(
        amount=int(package.price * 100),  # cents
        currency='usd',
        metadata={
            'package_id': package.pk,
            'client_id': client.pk,
            'type': 'package_purchase',
        },
    )

    # Create a pending Payment record
    Payment.objects.create(
        client=client,
        amount=package.price,
        stripe_payment_intent_id=intent.id,
        description=f'Package: {package.name}',
    )

    return JsonResponse({'client_secret': intent.client_secret})
```

### Frontend (add to the packages template)

```html
<script src="https://js.stripe.com/v3/"></script>
<script>
const stripe = Stripe('{{ stripe_public_key }}');

async function buyPackage(packageId) {
    const res = await fetch(`/client/packages/${packageId}/pay/`, {
        method: 'POST',
        headers: {'X-CSRFToken': '{{ csrf_token }}'},
    });
    const { client_secret } = await res.json();

    const { error } = await stripe.confirmCardPayment(client_secret, {
        payment_method: {
            card: cardElement,  // Stripe Elements card
            billing_details: { name: '{{ request.user.get_full_name }}' },
        },
    });

    if (error) {
        showError(error.message);
    } else {
        window.location.href = '/client/packages/?purchased=1';
    }
}
</script>
```

Pass `stripe_public_key` in the view context:
```python
context['stripe_public_key'] = settings.STRIPE_PUBLIC_KEY
```

### Webhook handler (confirms payment, activates package)

See Section 5 — the `payment_intent.succeeded` event activates the `ClientPackage`.

---

## 3. Flow 2 — Facility Rental Payment

**Trigger:** Owner approves a `FieldRentalSlot` request
**Stripe object:** `PaymentIntent` (created at approval time, collected from client)

### Option A: Charge at approval (send payment link via notification)

When `owner_field_slot_approve` is called, create a PaymentIntent and include the payment URL in the approval notification:

```python
# In admin_views.py > owner_field_slot_approve
import stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

intent = stripe.PaymentIntent.create(
    amount=int(slot.price * 100),
    currency='usd',
    metadata={
        'slot_id': slot.pk,
        'client_id': slot.booked_by_client.pk,
        'type': 'facility_rental',
    },
)

from payments.models import Payment
Payment.objects.create(
    client=slot.booked_by_client,
    amount=slot.price,
    stripe_payment_intent_id=intent.id,
    description=f'Facility Rental: {slot.date} {slot.start_time:%I:%M %p}–{slot.end_time:%I:%M %p}',
)

# Include payment link in the approval notification message
payment_url = f"{settings.SITE_URL}/client/rentals/{slot.pk}/pay/"
```

### Option B: Client pays when submitting the request (simplest)

Create the PaymentIntent during `field_rental_request` POST and require card capture before the request is submitted. The PaymentIntent status stays `requires_capture` until owner approves, then capture it.

```python
# Create with manual capture
intent = stripe.PaymentIntent.create(
    amount=int(slot.price * 100),
    currency='usd',
    capture_method='manual',  # hold the card, don't charge yet
    ...
)

# On owner approval:
stripe.PaymentIntent.capture(payment.stripe_payment_intent_id)
```

> **Recommended:** Option B for best UX — client pays upfront, owner captures on approval, auto-refunds if rejected.

---

## 4. Flow 3 — Recurring Subscriptions

**Trigger:** Client signs up for a monthly membership package
**Stripe objects:** `Customer`, `Price` (recurring), `Subscription`

### Setup in Stripe Dashboard
1. Create a **Product**: "Atletas World Monthly Membership"
2. Create a **Price**: recurring, monthly, e.g. $99/month
3. Copy the `price_id` (e.g. `price_xxx`) — store it on the `Package` model

### Add `stripe_price_id` to the Package model

```python
# clients/models.py — Package model
stripe_price_id = models.CharField(max_length=100, blank=True,
    help_text="Stripe Price ID for recurring packages (price_xxx)")
```

```bash
python manage.py makemigrations clients
python manage.py migrate
```

### Create subscription view

```python
@login_required
@require_POST
def create_subscription(request, package_id):
    package = get_object_or_404(Package, pk=package_id, is_active=True)
    client, _ = Client.objects.get_or_create(user=request.user)
    stripe.api_key = settings.STRIPE_SECRET_KEY

    # Get or create Stripe Customer
    if not client.stripe_customer_id:
        customer = stripe.Customer.create(
            email=request.user.email,
            name=request.user.get_full_name(),
            metadata={'client_id': client.pk},
        )
        client.stripe_customer_id = customer.id
        client.save()

    # Attach payment method from frontend
    payment_method_id = request.POST.get('payment_method_id')
    stripe.PaymentMethod.attach(payment_method_id, customer=client.stripe_customer_id)
    stripe.Customer.modify(client.stripe_customer_id,
        invoice_settings={'default_payment_method': payment_method_id})

    subscription = stripe.Subscription.create(
        customer=client.stripe_customer_id,
        items=[{'price': package.stripe_price_id}],
        expand=['latest_invoice.payment_intent'],
        metadata={'client_id': client.pk, 'package_id': package.pk},
    )

    return JsonResponse({
        'subscription_id': subscription.id,
        'status': subscription.status,
        'client_secret': subscription.latest_invoice.payment_intent.client_secret,
    })
```

Add `stripe_customer_id` to the `Client` model:
```python
stripe_customer_id = models.CharField(max_length=100, blank=True)
```

### Webhook events to handle
- `invoice.payment_succeeded` → extend `ClientPackage.expiry_date` by one month
- `customer.subscription.deleted` → mark `ClientPackage` as expired

---

## 5. Webhook Handler

All Stripe events land here. This is the single source of truth for payment confirmation — **never trust client-side redirects alone**.

### URL

```python
# atletasworld/urls.py
path('payments/webhook/', payments_webhook, name='payments_webhook'),
```

### View

```python
# payments/views.py
import stripe
import json
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

@csrf_exempt
def payments_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    event_type = event['type']
    data = event['data']['object']

    if event_type == 'payment_intent.succeeded':
        _handle_payment_succeeded(data)

    elif event_type == 'payment_intent.payment_failed':
        _handle_payment_failed(data)

    elif event_type == 'invoice.payment_succeeded':
        _handle_subscription_renewed(data)

    elif event_type == 'customer.subscription.deleted':
        _handle_subscription_cancelled(data)

    elif event_type == 'charge.refunded':
        _handle_refund(data)

    return HttpResponse(status=200)


def _handle_payment_succeeded(intent):
    from payments.models import Payment
    from clients.models import ClientPackage, Package, Client

    try:
        payment = Payment.objects.get(stripe_payment_intent_id=intent['id'])
        payment.status = 'succeeded'
        payment.stripe_charge_id = intent.get('latest_charge', '')
        payment.save()
    except Payment.DoesNotExist:
        return

    metadata = intent.get('metadata', {})
    payment_type = metadata.get('type')

    if payment_type == 'package_purchase':
        client = Client.objects.get(pk=metadata['client_id'])
        package = Package.objects.get(pk=metadata['package_id'])
        from datetime import date, timedelta
        ClientPackage.objects.create(
            client=client,
            package=package,
            status='active',
            sessions_remaining=package.sessions_included,
            expiry_date=date.today() + timedelta(weeks=package.validity_weeks),
        )

    elif payment_type == 'facility_rental':
        from clients.models import FieldRentalSlot
        slot = FieldRentalSlot.objects.get(pk=metadata['slot_id'])
        slot.payment_status = 'paid'
        slot.amount_paid = slot.price
        slot.save()


def _handle_payment_failed(intent):
    from payments.models import Payment
    try:
        payment = Payment.objects.get(stripe_payment_intent_id=intent['id'])
        payment.status = 'failed'
        payment.save()
    except Payment.DoesNotExist:
        pass


def _handle_subscription_renewed(invoice):
    from clients.models import ClientPackage
    subscription_id = invoice.get('subscription')
    if subscription_id:
        from datetime import date, timedelta
        cp = ClientPackage.objects.filter(
            stripe_subscription_id=subscription_id, status='active'
        ).first()
        if cp:
            cp.expiry_date = date.today() + timedelta(weeks=4)
            cp.save()


def _handle_subscription_cancelled(subscription):
    from clients.models import ClientPackage
    ClientPackage.objects.filter(
        stripe_subscription_id=subscription['id']
    ).update(status='expired')


def _handle_refund(charge):
    from payments.models import Payment
    try:
        payment = Payment.objects.get(stripe_charge_id=charge['id'])
        payment.status = 'refunded'
        payment.save()
    except Payment.DoesNotExist:
        pass
```

---

## 6. Flow 4 — Refunds

**Trigger:** Owner issues a refund from the owner portal

```python
# admin_views.py
import stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

@login_required
@user_passes_test(is_owner)
@require_POST
def owner_issue_refund(request, payment_id):
    from payments.models import Payment
    payment = get_object_or_404(Payment, pk=payment_id, status='succeeded')

    amount_cents = request.POST.get('amount')  # optional partial refund
    kwargs = {'payment_intent': payment.stripe_payment_intent_id}
    if amount_cents:
        kwargs['amount'] = int(float(amount_cents) * 100)

    try:
        stripe.Refund.create(**kwargs)
        # Status updated via webhook (charge.refunded)
        messages.success(request, f'Refund issued for ${payment.amount}.')
    except stripe.error.StripeError as e:
        messages.error(request, f'Refund failed: {e.user_message}')

    return redirect('owner_payments')
```

---

## 7. Test Cards

| Card number | Scenario |
|---|---|
| `4242 4242 4242 4242` | Payment succeeds |
| `4000 0000 0000 9995` | Card declined — insufficient funds |
| `4000 0025 0000 3155` | Requires 3D Secure authentication |
| `4000 0000 0000 0002` | Card declined — generic |

Use any future expiry date and any 3-digit CVC.

---

## 8. Local Webhook Testing

Use the Stripe CLI to forward events to your local server:

```bash
brew install stripe/stripe-cli/stripe
stripe login
stripe listen --forward-to localhost:8001/payments/webhook/
# Copy the webhook signing secret it prints → set as STRIPE_WEBHOOK_SECRET in .env
```

---

## 9. Going Live Checklist

- [ ] Switch `.env` keys from `pk_test_` / `sk_test_` to `pk_live_` / `sk_live_`
- [ ] Register production webhook in Stripe Dashboard → `https://atletasperformancecenter.com/payments/webhook/`
- [ ] Update `STRIPE_WEBHOOK_SECRET` with the live signing secret
- [ ] Test with a real card for $0.50 (minimum Stripe charge)
- [ ] Verify webhook events appear in Stripe Dashboard → Webhooks → Recent deliveries
