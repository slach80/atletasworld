"""
Stripe API helpers for the payments app.

Centralises Stripe client initialisation and customer management so that
all payment views share a single, consistently configured Stripe instance.
"""
import stripe
from django.conf import settings


def get_stripe():
    """Return the stripe module configured with the project's secret key.

    Call this instead of importing stripe directly so the API key is always
    set before any Stripe call is made.

    Returns:
        module: The stripe module with api_key set.
    """
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def get_or_create_stripe_customer(client):
    """Look up or create a Stripe Customer for the given Client.

    Caches the Stripe customer ID on the Client model to avoid creating
    duplicate customers on repeat purchases.

    Args:
        client: A Client model instance. Must have a related User.

    Returns:
        str: The Stripe customer ID (cus_xxx).
    """
    s = get_stripe()
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


# Keep legacy underscore-prefixed aliases so existing call-sites don't break
_stripe = get_stripe
_get_or_create_stripe_customer = get_or_create_stripe_customer
