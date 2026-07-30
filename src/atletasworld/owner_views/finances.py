from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum
from django.views.decorators.http import require_POST
from django.conf import settings
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_finances(request):
    """Revenue reporting, outstanding balances, and transaction history."""
    from clients.models import ClientPackage, Package
    from clients.models import FieldRentalSlot
    from payments.models import Payment
    from calendar import month_name
    from decimal import Decimal

    today = timezone.localdate()

    # --- Date range: default to current month, support ?month=M&year=Y ---
    try:
        view_month = int(request.GET.get('month', today.month))
        view_year  = int(request.GET.get('year',  today.year))
        if not (1 <= view_month <= 12):
            view_month = today.month
        if not (2000 <= view_year <= 2100):
            view_year = today.year
    except (ValueError, TypeError):
        view_month, view_year = today.month, today.year

    # Prev / next month navigation
    if view_month == 1:
        prev_month, prev_year = 12, view_year - 1
    else:
        prev_month, prev_year = view_month - 1, view_year
    if view_month == 12:
        next_month, next_year = 1, view_year + 1
    else:
        next_month, next_year = view_month + 1, view_year

    # ---- Revenue for selected month ----------------------------------------

    # Sessions paid directly
    from bookings.models import Booking
    session_revenue = Booking.objects.filter(
        scheduled_date__month=view_month,
        scheduled_date__year=view_year,
        payment_status='paid',
    ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0')

    # Package revenue = actual amount charged via Stripe (not list price)
    package_revenue = Payment.objects.filter(
        status='succeeded',
        created_at__month=view_month,
        created_at__year=view_year,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Facility rentals paid
    rental_revenue = FieldRentalSlot.objects.filter(
        approved_at__month=view_month,
        approved_at__year=view_year,
        payment_status='paid',
    ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0')

    total_revenue = session_revenue + package_revenue + rental_revenue

    # ---- Tax calculations --------------------------------------------------
    tax_rate = Decimal(str(getattr(settings, 'TAX_RATE', 0.0)))
    tax_amount = (total_revenue * tax_rate).quantize(Decimal('0.01'))
    revenue_after_tax = total_revenue - tax_amount
    tax_enabled = tax_rate > 0

    # ---- Stripe confirmed payments for this month (pre-wired for go-live) --
    stripe_confirmed = Payment.objects.filter(
        status='succeeded',
        created_at__month=view_month,
        created_at__year=view_year,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    stripe_count = Payment.objects.filter(
        status='succeeded',
        created_at__month=view_month,
        created_at__year=view_year,
    ).count()

    # ---- 6-month trend -----------------------------------------------------
    monthly_trend = []
    for i in range(5, -1, -1):
        # Walk back i months from view_month/view_year
        m = view_month - i
        y = view_year
        while m <= 0:
            m += 12
            y -= 1

        s = Booking.objects.filter(
            scheduled_date__month=m, scheduled_date__year=y, payment_status='paid'
        ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0')

        p = Payment.objects.filter(
            status='succeeded',
            created_at__month=m, created_at__year=y
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

        r = FieldRentalSlot.objects.filter(
            approved_at__month=m, approved_at__year=y, payment_status='paid'
        ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0')

        monthly_trend.append({
            'label': f"{month_name[m][:3]} {str(y)[2:]}",
            'sessions': float(s),
            'packages': float(p),
            'rentals':  float(r),
            'total':    float(s + p + r),
        })

    max_total = max((m['total'] for m in monthly_trend), default=1) or 1

    # ---- Outstanding balances (unpaid bookings) ----------------------------
    outstanding = Booking.objects.filter(
        payment_status='pending',
        status__in=['pending', 'confirmed'],
    ).select_related('client__user', 'player', 'session_type').order_by('scheduled_date')

    outstanding_total = outstanding.aggregate(
        total=Sum('session_type__price')
    )['total'] or Decimal('0')

    # ---- Recent transactions -----------------------------------------------
    recent_bookings = Booking.objects.filter(
        payment_status='paid',
        amount_paid__gt=0,
    ).select_related('client__user', 'player', 'session_type').order_by('-scheduled_date')[:15]

    _recent_packages_qs = list(ClientPackage.objects.exclude(
        status='cancelled'
    ).select_related('client__user', 'package').order_by('-purchase_date')[:10])

    # Attach actual charged amount and discount info to each package
    _pi_ids = [cp.stripe_payment_id for cp in _recent_packages_qs if cp.stripe_payment_id]
    _payments_by_pi = {
        p.stripe_payment_intent_id: p
        for p in Payment.objects.filter(stripe_payment_intent_id__in=_pi_ids)
    } if _pi_ids else {}
    from clients.models import DiscountCodeUse
    _uses_by_pkg = {
        u.applied_to_package_id: u
        for u in DiscountCodeUse.objects.filter(
            applied_to_package__in=[cp.id for cp in _recent_packages_qs],
            status='applied',
        ).select_related('code')
    }
    for cp in _recent_packages_qs:
        pay = _payments_by_pi.get(cp.stripe_payment_id)
        cp.charged_amount = pay.amount if pay else cp.package.price
        use = _uses_by_pkg.get(cp.id)
        cp.discount_label = use.code.code if use else None
        cp.discount_amount = use.discount_amount if use else None
    recent_packages = _recent_packages_qs

    recent_rentals = FieldRentalSlot.objects.filter(
        payment_status='paid',
    ).select_related('booked_by_client__user', 'service').order_by('-approved_at')[:10]

    # ---- Package sales summary for the month — use actual Payment amounts ----
    from django.db.models import Subquery, OuterRef
    pkg_payment_map = {
        p.stripe_payment_intent_id: p.amount
        for p in Payment.objects.filter(
            status='succeeded',
            created_at__month=view_month,
            created_at__year=view_year,
        )
    }
    _breakdown_qs = ClientPackage.objects.filter(
        purchase_date__month=view_month,
        purchase_date__year=view_year,
    ).exclude(status='cancelled').select_related('package')
    _bd = {}
    for cp in _breakdown_qs:
        name = cp.package.name
        charged = pkg_payment_map.get(cp.stripe_payment_id, cp.package.price)
        if name not in _bd:
            _bd[name] = {'package__name': name, 'count': 0, 'revenue': Decimal('0')}
        _bd[name]['count'] += 1
        _bd[name]['revenue'] += charged
    package_breakdown = sorted(_bd.values(), key=lambda x: x['revenue'], reverse=True)

    context = {
        'today': today,
        'view_month': view_month,
        'view_year': view_year,
        'view_month_name': month_name[view_month],
        'prev_month': prev_month, 'prev_year': prev_year,
        'next_month': next_month, 'next_year': next_year,
        # Revenue totals
        'session_revenue':    session_revenue,
        'package_revenue':    package_revenue,
        'rental_revenue':     rental_revenue,
        'total_revenue':      total_revenue,
        # Tax
        'tax_rate':           tax_rate,
        'tax_rate_pct':       float(tax_rate * 100),
        'tax_amount':         tax_amount,
        'revenue_after_tax':  revenue_after_tax,
        'tax_enabled':        tax_enabled,
        # Stripe
        'stripe_confirmed':   stripe_confirmed,
        'stripe_count':       stripe_count,
        'stripe_live':        bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_SECRET_KEY.startswith(('sk_live', 'rk_live'))),
        # Trend
        'monthly_trend':    monthly_trend,
        'max_total':        max_total,
        # Outstanding
        'outstanding':         outstanding[:20],
        'outstanding_total':   outstanding_total,
        'outstanding_count':   outstanding.count(),
        # Transactions
        'recent_bookings':  recent_bookings,
        'recent_packages':  recent_packages,
        'recent_rentals':   recent_rentals,
        # Package breakdown
        'package_breakdown': package_breakdown,
    }
    return render(request, 'owner/finances.html', context)


@login_required
@user_passes_test(is_owner)
def owner_payments(request):
    """List all Stripe payment records."""
    from payments.models import Payment
    payments = Payment.objects.filter(
        client__user__is_staff=False,
        client__user__is_superuser=False,
    ).select_related('client__user').order_by('-created_at')[:100]
    context = {
        'payments': payments,
        'stripe_live': bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_SECRET_KEY.startswith(('sk_live', 'rk_live'))),
    }
    return render(request, 'owner/payments.html', context)


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_issue_refund(request, payment_id):
    """Issue a full or partial Stripe refund."""
    from payments.models import Payment
    from django.shortcuts import get_object_or_404

    if not settings.STRIPE_SECRET_KEY:
        messages.error(request, 'Stripe is not configured.')
        return redirect('owner_payments')

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    payment = get_object_or_404(Payment, pk=payment_id, status='succeeded')
    amount_str = request.POST.get('amount', '').strip()

    try:
        kwargs = {'payment_intent': payment.stripe_payment_intent_id}
        if amount_str:
            kwargs['amount'] = int(Decimal(amount_str) * 100)
        stripe.Refund.create(**kwargs)
        messages.success(request, f'Refund initiated for {payment.client} — ${payment.amount}. Status updates via webhook.')
    except stripe.error.StripeError as e:
        messages.error(request, f'Refund failed: {e.user_message}')

    return redirect('owner_payments')
