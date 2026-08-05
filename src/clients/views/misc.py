from datetime import timedelta

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
from django.db.models import Sum

from clients.models import Client, NotificationPreference, DiscountCode, UnsubscribeToken


@login_required
@require_POST
def discount_validate(request):
    """
    AJAX: validate a promo code and return discount details.
    Rate-limited to 10 req/min per user to prevent code enumeration.
    POST JSON: { code, context ("package"|"session"), amount, target_id (optional) }
    """
    rl_key = f'discount_validate:{request.user.pk}'
    rl_count = cache.get(rl_key, 0)
    if rl_count >= 10:
        return JsonResponse({'valid': False, 'error': 'Too many requests. Please wait a moment.'}, status=429)
    cache.set(rl_key, rl_count + 1, timeout=60)

    import json
    from decimal import Decimal

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'valid': False, 'error': 'Invalid request.'}, status=400)

    code_str  = body.get('code', '').strip().upper()
    context   = body.get('context', 'package')
    target_id = body.get('target_id')
    try:
        subtotal = Decimal(str(body.get('amount', '0')))
    except Exception:
        return JsonResponse({'valid': False, 'error': 'Invalid amount.'}, status=400)

    if not code_str:
        return JsonResponse({'valid': False, 'error': 'Please enter a promo code.'})

    try:
        dc = DiscountCode.objects.get(code=code_str)
    except DiscountCode.DoesNotExist:
        return JsonResponse({'valid': False, 'error': 'Invalid promo code.'})

    ok, err = dc.is_valid_now()
    if not ok:
        return JsonResponse({'valid': False, 'error': err})

    if dc.scope == 'packages' and context != 'package':
        return JsonResponse({'valid': False, 'error': 'This code is only valid for package purchases.'})
    if dc.scope == 'sessions' and context != 'session':
        return JsonResponse({'valid': False, 'error': 'This code is only valid for drop-in sessions.'})

    if target_id:
        if context == 'package' and dc.specific_packages.exists():
            if not dc.specific_packages.filter(pk=target_id).exists():
                return JsonResponse({'valid': False, 'error': 'This code does not apply to this package.'})
        if context == 'session' and dc.specific_session_types.exists():
            if not dc.specific_session_types.filter(pk=target_id).exists():
                return JsonResponse({'valid': False, 'error': 'This code does not apply to this session type.'})

    if dc.min_purchase_amount and subtotal < dc.min_purchase_amount:
        return JsonResponse({
            'valid': False,
            'error': f'Minimum purchase of ${dc.min_purchase_amount} required.',
        })

    client, _ = Client.objects.get_or_create(user=request.user)
    client_uses = dc.uses.filter(client=client, status='applied').count()
    if client_uses >= dc.max_uses_per_client:
        return JsonResponse({'valid': False, 'error': 'You have already used this code.'})

    discount_amount = dc.compute_discount(subtotal)
    final_amount    = subtotal - discount_amount

    msg = (f'{dc.value}% off applied' if dc.discount_type == 'percent'
           else f'${discount_amount} off applied')

    return JsonResponse({
        'valid': True,
        'code': dc.code,
        'discount_type': dc.discount_type,
        'value': str(dc.value),
        'discount_amount': str(discount_amount),
        'final_amount': str(final_amount),
        'message': msg,
    })


def unsubscribe_landing(request, token):
    """Public unsubscribe page — no login required. Shows survey + preference checkboxes."""
    try:
        obj = UnsubscribeToken.objects.select_related('client__user', 'client__notification_preferences').get(token=token)
    except UnsubscribeToken.DoesNotExist:
        return render(request, 'clients/unsubscribe.html', {'invalid': True})

    if not obj.is_valid():
        return render(request, 'clients/unsubscribe.html', {'expired': True})

    client = obj.client
    prefs, _ = NotificationPreference.objects.get_or_create(client=client)

    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        reason_other = request.POST.get('reason_other', '').strip()

        selected_fields = request.POST.getlist('notification_types')
        all_fields = [
            'booking_confirmations', 'booking_reminders', 'booking_cancellations',
            'purchase_confirmations', 'assessment_notifications', 'promotional_updates',
        ]
        for field in all_fields:
            if field in selected_fields:
                setattr(prefs, field, 'none')
        prefs.save()

        return render(request, 'clients/unsubscribe.html', {
            'done': True,
            'client': client,
            'unsubscribed': selected_fields,
            'token': token,
        })

    reasons = [
        ('too_many', 'Too many emails'),
        ('not_relevant', 'Not relevant to me'),
        ('no_longer_client', "I'm no longer a client"),
        ('prefer_phone', 'I prefer phone/text'),
        ('other', 'Other'),
    ]
    return render(request, 'clients/unsubscribe.html', {
        'client': client,
        'prefs': prefs,
        'token': token,
        'reasons': reasons,
    })


def unsubscribe_oneclick(request, token):
    """One-click, no-questions-asked unsubscribe via a signed email-address token.

    The signed token works for ANY recipient — clients, coaches, or bare contacts —
    so the link in every email footer immediately stops all future emails. For a
    matching Client we also flip the master ``email_opt_out`` flag so granular
    preferences stay in sync. A resubscribe link is offered on the confirmation page.
    """
    from django.core import signing
    from clients.models import EmailSuppression, UNSUBSCRIBE_SALT

    try:
        email = signing.loads(token, salt=UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return render(request, 'clients/unsubscribe.html', {'invalid': True})

    resubscribe = request.GET.get('resubscribe') == '1' or request.POST.get('resubscribe') == '1'

    if resubscribe:
        EmailSuppression.resubscribe(email)
        client = Client.objects.filter(user__email__iexact=email).first()
        if client:
            try:
                prefs = client.notification_preferences
                prefs.email_opt_out = False
                prefs.email_opt_out_at = None
                prefs.save(update_fields=['email_opt_out', 'email_opt_out_at'])
            except NotificationPreference.DoesNotExist:
                pass
        return render(request, 'clients/unsubscribe.html', {
            'resubscribed': True,
            'email': email,
            'token': token,
        })

    # No questions asked — suppress immediately.
    EmailSuppression.suppress(email, reason='one-click email footer')
    client = Client.objects.filter(user__email__iexact=email).first()
    if client:
        prefs, _ = NotificationPreference.objects.get_or_create(client=client)
        prefs.email_opt_out = True
        prefs.email_opt_out_at = timezone.now()
        prefs.save(update_fields=['email_opt_out', 'email_opt_out_at'])

    return render(request, 'clients/unsubscribe.html', {
        'oneclick_done': True,
        'email': email,
        'token': token,
    })


@login_required
def referral_page(request):
    """Client referral page — show code, share link, history, rewards."""
    from clients.models import ReferralCode, Referral, ClientCredit
    from clients.services import ReferralService

    client, _ = Client.objects.get_or_create(user=request.user)

    # Get or create referral code for this user
    referral_code = ReferralService.get_or_create_code(request.user)

    # Build share link
    site_url = getattr(settings, 'SITE_URL', 'https://atletasperformancecenter.com')
    share_link = f"{site_url}/accounts/signup/?ref={referral_code.code}"

    # Check if user was referred by someone
    was_referred = Referral.objects.filter(referred_user=request.user).exists()

    # Referrals given by this user
    referrals_given = Referral.objects.filter(
        referrer_user=request.user
    ).select_related('referred_user').order_by('-created_at')

    # Referral credits earned
    referral_credits = ClientCredit.objects.filter(
        client=client,
        referral__isnull=False
    ).select_related('referral').order_by('-created_at')

    # Stats
    total_referrals = referrals_given.count()
    activated_referrals = referrals_given.filter(status='activated').count()
    total_rewards = referral_credits.aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'client': client,
        'referral_code': referral_code,
        'share_link': share_link,
        'was_referred': was_referred,
        'referrals_given': referrals_given,
        'referral_credits': referral_credits,
        'total_referrals': total_referrals,
        'activated_referrals': activated_referrals,
        'total_rewards': total_rewards,
    }
    return render(request, 'clients/referral.html', context)


@login_required
@require_POST
def add_referral_code(request):
    """Allow user to retroactively add a referral code if they signed up without one."""
    from clients.models import ReferralCode, Referral
    from django.db import transaction
    import logging

    logger = logging.getLogger(__name__)

    # Check if user already has a referral
    if Referral.objects.filter(referred_user=request.user).exists():
        messages.error(request, "You already have a referral on your account.")
        return redirect('clients:referral')

    code = request.POST.get('referral_code', '').strip().upper()

    if not code:
        messages.error(request, "Please enter a referral code.")
        return redirect('clients:referral')

    try:
        referral_code = ReferralCode.objects.get(code=code)
    except ReferralCode.DoesNotExist:
        messages.error(request, "Invalid referral code. Please check and try again.")
        return redirect('clients:referral')

    # Prevent self-referral
    if referral_code.user == request.user:
        messages.error(request, "You cannot use your own referral code.")
        return redirect('clients:referral')

    # Create referral
    try:
        with transaction.atomic():
            referrer_type = 'coach' if referral_code.user.groups.filter(name='Coach').exists() else 'client'

            Referral.objects.create(
                referrer_user=referral_code.user,
                referred_user=request.user,
                referral_code=code,
                referrer_type=referrer_type,
                status='pending',
                referral_window_expires=timezone.now() + timedelta(days=60)
            )

            messages.success(
                request,
                f"Referral code applied! When you make your first purchase, "
                f"{referral_code.user.get_full_name() or referral_code.user.username} will receive their reward."
            )
            logger.info(f"Retroactive referral added: {request.user.username} referred by {referral_code.user.username}")

    except Exception as e:
        logger.exception(f"Error creating retroactive referral: {e}")
        messages.error(request, "An error occurred. Please try again or contact support.")

    return redirect('clients:referral')


# ============================================================================
# APC SELECT — RSVP
# ============================================================================

@login_required
@require_POST
def select_game_rsvp(request, game_id):
    """Client RSVP endpoint for a Select game. POST only.

    The dashboard's RSVP buttons are plain HTML forms (full-page POST, no JS
    interception), so this must redirect back rather than return raw JSON —
    returning JSON here left the client's whole browser tab showing a bare
    '{"ok": true, ...}' page instead of the dashboard after every RSVP click.
    """
    from bookings.models import SelectGame, SelectGameRSVP

    client, _ = Client.objects.get_or_create(user=request.user)

    try:
        game = SelectGame.objects.get(pk=game_id, status='published')
    except SelectGame.DoesNotExist:
        messages.error(request, 'Game not found.')
        return redirect('clients:dashboard')

    # Must have an RSVP record (created by fan-out signal) to respond
    try:
        rsvp = SelectGameRSVP.objects.get(game=game, client=client)
    except SelectGameRSVP.DoesNotExist:
        messages.error(request, 'You are not invited to this game.')
        return redirect('clients:dashboard')

    rsvp_status = request.POST.get('status')
    if rsvp_status not in ('coming', 'not_coming'):
        messages.error(request, 'Invalid RSVP status.')
        return redirect('clients:dashboard')

    rsvp.status = rsvp_status
    rsvp.save(update_fields=['status', 'updated_at'])
    messages.success(
        request,
        f"RSVP updated — you're marked as {'Going' if rsvp_status == 'coming' else 'Not Going'}."
    )

    return redirect('clients:dashboard')
