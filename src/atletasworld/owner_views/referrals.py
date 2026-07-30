from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_referrals(request):
    """Owner referral dashboard — stats, all referrals, pending payouts."""
    from clients.models import Referral, ReferralPayout, ClientCredit
    from django.db.models import Sum, Count, Q

    # Stats
    total_referrals = Referral.objects.count()
    activated = Referral.objects.filter(status='activated').count()
    pending = Referral.objects.filter(status='pending').count()
    expired = Referral.objects.filter(status='expired').count()

    total_client_rewards = ClientCredit.objects.filter(referral__isnull=False).aggregate(
        total=Sum('amount')
    )['total'] or 0

    total_coach_payouts = ReferralPayout.objects.filter(status__in=['approved', 'paid']).aggregate(
        total=Sum('amount')
    )['total'] or 0

    pending_payout_amount = ReferralPayout.objects.filter(status='pending').aggregate(
        total=Sum('amount')
    )['total'] or 0

    # All referrals
    referrals = Referral.objects.select_related(
        'referrer_user', 'referred_user'
    ).order_by('-created_at')

    # Pending payouts (for coach referrals)
    pending_payouts = ReferralPayout.objects.filter(
        status='pending'
    ).select_related('referral__referrer_user', 'referral__referred_user', 'coach_user').order_by('-created_at')

    context = {
        'total_referrals': total_referrals,
        'activated': activated,
        'pending': pending,
        'expired': expired,
        'total_client_rewards': total_client_rewards,
        'total_coach_payouts': total_coach_payouts,
        'pending_payout_amount': pending_payout_amount,
        'referrals': referrals,
        'pending_payouts': pending_payouts,
    }
    return render(request, 'owner/referrals.html', context)


@login_required
@user_passes_test(is_owner)
def owner_referral_payouts(request):
    """Owner referral payout history — all payouts with filters."""
    from clients.models import ReferralPayout

    status_filter = request.GET.get('status', 'all')

    payouts = ReferralPayout.objects.select_related(
        'referral__referrer_user', 'referral__referred_user', 'coach_user', 'reviewed_by'
    ).order_by('-created_at')

    if status_filter != 'all':
        payouts = payouts.filter(status=status_filter)

    context = {
        'payouts': payouts,
        'status_filter': status_filter,
    }
    return render(request, 'owner/referral_payouts.html', context)


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_payout_approve(request, payout_id):
    """Approve a referral payout."""
    from clients.models import ReferralPayout

    payout = get_object_or_404(ReferralPayout, id=payout_id)

    if payout.status != 'pending':
        messages.error(request, 'Payout is not pending.')
        return redirect('owner_referrals')

    payout.status = 'approved'
    payout.reviewed_by = request.user
    payout.reviewed_at = timezone.now()
    payout.save()

    messages.success(request, f'Payout of ${payout.amount} to {payout.coach_user.get_full_name()} approved.')
    return redirect('owner_referrals')


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_payout_reject(request, payout_id):
    """Reject a referral payout."""
    from clients.models import ReferralPayout

    payout = get_object_or_404(ReferralPayout, id=payout_id)

    if payout.status != 'pending':
        messages.error(request, 'Payout is not pending.')
        return redirect('owner_referrals')

    rejection_reason = request.POST.get('rejection_reason', '').strip()

    payout.status = 'rejected'
    payout.reviewed_by = request.user
    payout.reviewed_at = timezone.now()
    payout.rejection_reason = rejection_reason
    payout.save()

    messages.success(request, f'Payout of ${payout.amount} to {payout.coach_user.get_full_name()} rejected.')
    return redirect('owner_referrals')


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_payout_mark_paid(request, payout_id):
    """Mark a referral payout as paid."""
    from clients.models import ReferralPayout

    payout = get_object_or_404(ReferralPayout, id=payout_id)

    if payout.status != 'approved':
        messages.error(request, 'Payout is not approved.')
        return redirect('owner_referrals')

    payment_notes = request.POST.get('payment_notes', '').strip()

    payout.status = 'paid'
    payout.paid_at = timezone.now()
    payout.payment_notes = payment_notes
    payout.save()

    messages.success(request, f'Payout of ${payout.amount} to {payout.coach_user.get_full_name()} marked as paid.')
    return redirect('owner_referrals')
