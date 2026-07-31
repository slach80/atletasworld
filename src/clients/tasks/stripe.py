"""
Celery tasks for Stripe health monitoring.
"""
from celery import shared_task
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


# ── Stripe Health Check ────────────────────────────────────────────────────────

STRIPE_ALERT_RECIPIENT = 'info@atletasperformancecenter.com'


@shared_task(name='clients.tasks.check_stripe_health')
def check_stripe_health():
    """
    Daily health check for Stripe connectivity.
    Sends an alert email to info@ if:
      - STRIPE_SECRET_KEY is missing or empty
      - The key is in test mode (sk_test_) instead of live (sk_live_)
      - The Stripe API call fails (network error, invalid key, etc.)
    """
    from django.core.mail import send_mail

    key = getattr(settings, 'STRIPE_SECRET_KEY', '') or ''

    issues = []

    if not key:
        issues.append('STRIPE_SECRET_KEY is not set.')
    elif not key.startswith(('sk_live', 'rk_live')):
        issues.append(f'Stripe key is in TEST mode (starts with "{key[:10]}…"). Switch to a live key for real payments.')

    if key:
        try:
            import stripe
            stripe.api_key = key
            stripe.Balance.retrieve()
        except Exception as e:
            issues.append(f'Stripe API connection failed: {e}')

    if issues:
        body = (
            "⚠️ Stripe Health Alert — Atletas Performance Center\n\n"
            + "\n".join(f"• {issue}" for issue in issues)
            + "\n\nPlease review your Stripe configuration at "
            "https://atletasperformancecenter.com/owner-portal/payments/\n"
        )
        try:
            send_mail(
                subject='⚠️ Stripe Connection Issue — APC',
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[STRIPE_ALERT_RECIPIENT],
                fail_silently=False,
            )
            logger.warning(f"check_stripe_health: alert sent — {issues}")
        except Exception as e:
            logger.error(f"check_stripe_health: failed to send alert email: {e}")
        return f"Alert sent: {issues}"

    logger.info("check_stripe_health: Stripe OK")
    return "OK"
