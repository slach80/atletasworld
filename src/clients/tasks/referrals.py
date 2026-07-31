"""
Celery tasks for the referral program.
"""
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


# ── Referral Program Tasks ──────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=3, name='clients.tasks.grant_referral_reward')
def grant_referral_reward(self, referral_id):
    """
    Grant referral reward after first purchase.

    - Client referrers: Create ClientCredit with 60-day expiry
    - Coach referrers: Create ReferralPayout for owner review

    Called by ReferralService.check_and_activate() after a referral is activated.
    """
    from clients.models import Referral, ClientCredit, ReferralPayout
    from decimal import Decimal

    try:
        referral = Referral.objects.select_related('referrer_user', 'referred_user').get(id=referral_id)
    except Referral.DoesNotExist:
        logger.error(f"grant_referral_reward: Referral {referral_id} not found")
        return "Referral not found"

    if referral.status != 'activated':
        logger.warning(f"grant_referral_reward: Referral {referral_id} not activated (status={referral.status})")
        return "Referral not activated"

    if not referral.reward_amount or referral.reward_amount <= Decimal('0'):
        logger.error(f"grant_referral_reward: Referral {referral_id} has no reward_amount")
        return "No reward amount"

    try:
        if referral.referrer_type == 'client':
            # Grant store credit to client referrer
            from clients.models import Client
            try:
                referrer_client = Client.objects.get(user=referral.referrer_user)
            except Client.DoesNotExist:
                logger.error(f"grant_referral_reward: Client profile not found for user {referral.referrer_user.pk}")
                return "Client profile not found"

            expiry_date = timezone.localdate() + timedelta(days=60)

            credit, created = ClientCredit.objects.get_or_create(
                client=referrer_client,
                referral=referral,
                defaults={
                    'amount': referral.reward_amount,
                    'balance': referral.reward_amount,
                    'reason': f'Referral reward: {referral.referred_user.get_full_name() or referral.referred_user.username} joined',
                    'expiry_date': expiry_date,
                }
            )

            if not created:
                logger.warning(f"grant_referral_reward: Credit already exists for referral {referral_id}")
                return "Credit already exists"

            logger.info(f"Granted ${referral.reward_amount} credit to client {referrer_client} for referral {referral_id}")
            return f"Granted ${referral.reward_amount} credit to {referrer_client.user.get_full_name()}"

        elif referral.referrer_type == 'coach':
            # Create payout request for coach referrer
            payout, created = ReferralPayout.objects.get_or_create(
                referral=referral,
                defaults={
                    'coach_user': referral.referrer_user,
                    'amount': referral.reward_amount,
                    'status': 'pending',
                }
            )

            if not created:
                logger.warning(f"grant_referral_reward: Payout already exists for referral {referral_id}")
                return "Payout already exists"

            logger.info(f"Created ${referral.reward_amount} payout request for coach {referral.referrer_user} (referral {referral_id})")
            return f"Created ${referral.reward_amount} payout request for {referral.referrer_user.get_full_name()}"

        else:
            logger.error(f"grant_referral_reward: Unknown referrer_type '{referral.referrer_type}' for referral {referral_id}")
            return f"Unknown referrer_type: {referral.referrer_type}"

    except Exception as e:
        logger.exception(f"grant_referral_reward: failed for referral {referral_id}")
        raise self.retry(exc=e, countdown=60)


@shared_task(name='clients.tasks.expire_stale_referrals')
def expire_stale_referrals():
    """
    Mark referrals as expired if the 60-day window has passed without activation.

    Runs daily at 3 AM via Celery Beat.
    """
    from clients.models import Referral

    expired_count = Referral.objects.filter(
        status='pending',
        referral_window_expires__lt=timezone.now()
    ).update(status='expired')

    logger.info(f"expire_stale_referrals: marked {expired_count} referrals as expired")
    return f"Marked {expired_count} referrals as expired"
