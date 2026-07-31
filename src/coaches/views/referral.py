from django.shortcuts import render
from coaches.models import Coach
from ._auth import coach_required


@coach_required
def referral_page(request):
    """Coach referral page — show code, share link, history, payouts."""
    from clients.models import ReferralCode, Referral, ReferralPayout
    from clients.services import ReferralService
    from django.db.models import Sum
    from django.conf import settings

    coach = request.coach

    # Get or create referral code
    referral_code = ReferralService.get_or_create_code(request.user)

    # Build share link
    site_url = getattr(settings, 'SITE_URL', 'https://atletasperformancecenter.com')
    share_link = f"{site_url}/signup?ref={referral_code.code}"

    # Referrals given by this coach
    referrals_given = Referral.objects.filter(
        referrer_user=request.user
    ).select_related('referred_user').order_by('-created_at')

    # Payouts
    payouts = ReferralPayout.objects.filter(
        coach_user=request.user
    ).select_related('referral').order_by('-created_at')

    # Stats
    total_referrals = referrals_given.count()
    activated_referrals = referrals_given.filter(status='activated').count()
    total_earned = payouts.filter(status__in=['approved', 'paid']).aggregate(total=Sum('amount'))['total'] or 0
    pending_amount = payouts.filter(status='pending').aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'coach': coach,
        'referral_code': referral_code,
        'share_link': share_link,
        'referrals_given': referrals_given,
        'payouts': payouts,
        'total_referrals': total_referrals,
        'activated_referrals': activated_referrals,
        'total_earned': total_earned,
        'pending_amount': pending_amount,
    }
    return render(request, 'coaches/referral.html', context)
