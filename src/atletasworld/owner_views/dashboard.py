from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Sum, Q, Case, When, Value, DecimalField
from coaches.models import Coach, ScheduleBlock
from bookings.models import Booking, SessionType
from clients.models import Client, Player, ClientPackage, FieldRentalSlot, ClientWaiver
from django.conf import settings
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_dashboard(request):
    """Owner dashboard with overview across all entities."""
    today = timezone.localdate()
    month_start = today.replace(day=1)
    year_start  = today.replace(month=1, day=1)

    # Aware datetime boundaries for DateTimeField comparisons (avoids naive-datetime warnings)
    def _dt(d):
        from datetime import datetime as _datetime
        return timezone.make_aware(_datetime(d.year, d.month, d.day))

    month_start_dt     = _dt(month_start)
    year_start_dt      = _dt(year_start)

    # ── Core counts ────────────────────────────────────────────────────────────
    total_coaches  = Coach.objects.filter(is_active=True).count()
    _client_qs = Client.objects.filter(user__is_staff=False, user__is_superuser=False
                   ).exclude(user__groups__name__in=['Owner', 'Coach'])
    total_clients  = _client_qs.count()
    total_players  = Player.objects.filter(is_active=True).count()
    pending_approvals = _client_qs.filter(approval_status='pending').count()

    # ── Today ──────────────────────────────────────────────────────────────────
    todays_bookings      = Booking.objects.filter(scheduled_date=today).count()
    total_sessions_today = ScheduleBlock.objects.filter(date=today).count()
    pending_bookings     = Booking.objects.filter(status__in=['pending', 'confirmed'],
                                                   scheduled_date__gte=today).count()

    # ── Financial ──────────────────────────────────────────────────────────────
    last_month_start    = (month_start - timedelta(days=1)).replace(day=1)
    last_month_start_dt = _dt(last_month_start)
    today_dt            = _dt(today + timedelta(days=1))  # exclusive upper bound (end of today)

    # 1 query: all booking drop-in revenue periods via conditional Sum
    # scheduled_date is DateField so date comparisons are correct here
    booking_rev = Booking.objects.filter(payment_status='paid').aggregate(
        this_month=Sum(Case(When(scheduled_date__gte=month_start, scheduled_date__lte=today,   then='amount_paid'), default=Value(0), output_field=DecimalField())),
        ytd=       Sum(Case(When(scheduled_date__gte=year_start,  scheduled_date__lte=today,   then='amount_paid'), default=Value(0), output_field=DecimalField())),
        last_month=Sum(Case(When(scheduled_date__gte=last_month_start, scheduled_date__lt=month_start, then='amount_paid'), default=Value(0), output_field=DecimalField())),
    )
    # 1 query: package revenue = actual amount charged (Payment.amount, status=succeeded)
    from payments.models import Payment as _Payment
    pkg_rev = _Payment.objects.filter(status='succeeded').aggregate(
        this_month=Sum(Case(When(created_at__gte=month_start_dt, created_at__lt=today_dt,        then='amount'), default=Value(0), output_field=DecimalField())),
        ytd=       Sum(Case(When(created_at__gte=year_start_dt,  created_at__lt=today_dt,        then='amount'), default=Value(0), output_field=DecimalField())),
        last_month=Sum(Case(When(created_at__gte=last_month_start_dt, created_at__lt=month_start_dt, then='amount'), default=Value(0), output_field=DecimalField())),
    )
    # 1 query: all rental revenue periods (approved_at is DateTimeField — use aware datetimes)
    rental_rev = FieldRentalSlot.objects.filter(payment_status='paid').aggregate(
        this_month=Sum(Case(When(approved_at__gte=month_start_dt, approved_at__lt=today_dt,        then='amount_paid'), default=Value(0), output_field=DecimalField())),
        ytd=       Sum(Case(When(approved_at__gte=year_start_dt,  approved_at__lt=today_dt,        then='amount_paid'), default=Value(0), output_field=DecimalField())),
        last_month=Sum(Case(When(approved_at__gte=last_month_start_dt, approved_at__lt=month_start_dt, then='amount_paid'), default=Value(0), output_field=DecimalField())),
    )
    revenue_this_month = (booking_rev['this_month'] or 0) + (pkg_rev['this_month'] or 0) + (rental_rev['this_month'] or 0)
    revenue_ytd        = (booking_rev['ytd']        or 0) + (pkg_rev['ytd']        or 0) + (rental_rev['ytd']        or 0)
    revenue_last_month = (booking_rev['last_month'] or 0) + (pkg_rev['last_month'] or 0) + (rental_rev['last_month'] or 0)
    pending_payments_qs = Booking.objects.filter(
        payment_status='pending', status__in=['pending', 'confirmed']
    ).select_related('client__user', 'player', 'session_type', 'coach__user').order_by('scheduled_date')
    pending_payments = pending_payments_qs.aggregate(t=Sum('amount_paid'))['t'] or 0
    rental_revenue_month = FieldRentalSlot.objects.filter(
        status='booked',
        date__gte=month_start, date__lte=today
    ).aggregate(t=Sum('service__price'))['t'] or 0

    # Recent paid transactions — drop-ins + package purchases
    _raw_bookings = Booking.objects.filter(
        payment_status='paid', amount_paid__gt=0
    ).select_related('client__user', 'player', 'session_type').order_by('-updated_at')[:8]
    _raw_packages = list(ClientPackage.objects.exclude(
        status='cancelled'
    ).select_related('client__user', 'package', 'player').order_by('-purchase_date')[:8])

    # Resolve actual charged amounts and discount labels for package rows
    from payments.models import Payment as _Payment
    from clients.models import DiscountCodeUse as _DiscountCodeUse
    _pi_ids = [cp.stripe_payment_id for cp in _raw_packages if cp.stripe_payment_id]
    _pay_map = {
        p.stripe_payment_intent_id: p.amount
        for p in _Payment.objects.filter(stripe_payment_intent_id__in=_pi_ids)
    } if _pi_ids else {}
    _use_map = {
        u.applied_to_package_id: u
        for u in _DiscountCodeUse.objects.filter(
            applied_to_package__in=[cp.id for cp in _raw_packages],
            status='applied',
        ).select_related('code')
    }

    _transactions = []
    for bk in _raw_bookings:
        _transactions.append({
            'name': (f"{bk.player.first_name} {bk.player.last_name}".strip()
                     if bk.player else (bk.client.user.get_full_name() or bk.client.user.email)),
            'label': bk.session_type.name if bk.session_type else 'Session',
            'amount': bk.amount_paid,
            'date': bk.updated_at.date(),
            'type': 'dropin',
            'discount_label': None,
            'discount_amount': None,
            'list_price': None,
        })
    for cp in _raw_packages:
        use = _use_map.get(cp.id)
        charged = _pay_map.get(cp.stripe_payment_id, cp.package.price)
        _transactions.append({
            'name': (f"{cp.player.first_name} {cp.player.last_name}".strip()
                     if cp.player else (cp.client.user.get_full_name() or cp.client.user.email)),
            'label': cp.package.name,
            'amount': charged,
            'date': cp.purchase_date.date(),
            'type': 'package',
            'discount_label': use.code.code if use else None,
            'discount_amount': use.discount_amount if use else None,
            'list_price': cp.package.price if use else None,
        })
    _transactions.sort(key=lambda x: x['date'], reverse=True)
    recent_transactions = _transactions[:8]

    # ── Coaches ────────────────────────────────────────────────────────────────
    coaches = Coach.objects.filter(is_active=True).annotate(
        sessions_today=Count('schedule_blocks', filter=Q(schedule_blocks__date=today), distinct=True),
        upcoming=Count('bookings', filter=Q(bookings__scheduled_date__gte=today,
                                            bookings__status__in=['pending','confirmed']), distinct=True),
        total_players=Count('bookings__player', distinct=True)
    ).order_by('-sessions_today')[:10]

    todays_schedule = ScheduleBlock.objects.filter(
        date=today
    ).select_related('coach__user').order_by('start_time')[:20]

    recent_bookings = Booking.objects.select_related(
        'client__user', 'player', 'coach__user', 'session_type'
    ).order_by('-created_at')[:10]

    players_pending_assessment = Booking.objects.filter(
        status='completed',
        scheduled_date__gte=today - timedelta(days=14)
    ).exclude(assessments__isnull=False).select_related('player', 'coach__user')[:10]

    pending_confirmation_list = Booking.objects.filter(
        status='pending',
        scheduled_date__gte=today,
    ).exclude(
        client__user__is_staff=True
    ).select_related('client__user', 'player', 'coach__user', 'session_type').order_by('scheduled_date')[:20]

    # ── Rentals ────────────────────────────────────────────────────────────────
    rentals_pending  = FieldRentalSlot.objects.filter(status='pending_approval').count()
    rentals_upcoming = FieldRentalSlot.objects.filter(
        status='booked', date__gte=today
    ).count()
    rentals_today = FieldRentalSlot.objects.filter(
        date=today, status__in=['booked','pending_approval']
    ).select_related('service').order_by('start_time')[:5]

    # ── Waivers ────────────────────────────────────────────────────────────────
    from clients.models import ClientWaiver
    current_year = today.year
    waiver_signed_count = ClientWaiver.objects.filter(
        valid_year=current_year,
        waiver_version=ClientWaiver.WAIVER_VERSION,
    ).values('client_id').distinct().count()
    waiver_unsigned_count = _client_qs.filter(
        user__groups__name='Client'
    ).exclude(
        waivers__valid_year=current_year,
        waivers__waiver_version=ClientWaiver.WAIVER_VERSION,
    ).count()

    # ── Active Packages ────────────────────────────────────────────────────────
    active_packages_count  = ClientPackage.objects.filter(
        status='active', expiry_date__gte=today
    ).count()
    expiring_soon_packages = ClientPackage.objects.filter(
        status='active',
        expiry_date__gte=today,
        expiry_date__lte=today + timedelta(days=7)
    ).select_related('client__user', 'package').order_by('expiry_date')[:8]
    packages_exhausted = ClientPackage.objects.filter(
        status='exhausted', expiry_date__gte=today
    ).count()

    # Package breakdown by type for dashboard tile
    _type_order = ['select', 'special', 'standard', 'team']
    _type_labels = {'select': 'Select', 'special': 'Summer/Camp', 'standard': 'Standard', 'team': 'Team'}
    _soon = today + timedelta(days=14)
    _breakdown_raw = {}
    for cp in ClientPackage.objects.filter(status__in=['active', 'exhausted'], expiry_date__gte=today).select_related('package'):
        pt = cp.package.package_type or 'standard'
        if pt not in _breakdown_raw:
            _breakdown_raw[pt] = {'active': 0, 'expiring': 0, 'exhausted': 0}
        if cp.status == 'active':
            _breakdown_raw[pt]['active'] += 1
            if cp.expiry_date <= _soon:
                _breakdown_raw[pt]['expiring'] += 1
        elif cp.status == 'exhausted':
            _breakdown_raw[pt]['exhausted'] += 1
    packages_breakdown = [
        {'label': _type_labels.get(pt, pt.title()), 'type': pt, **counts}
        for pt, counts in sorted(_breakdown_raw.items(), key=lambda x: _type_order.index(x[0]) if x[0] in _type_order else 99)
        if counts['active'] or counts['exhausted']
    ]

    # ── Stripe ─────────────────────────────────────────────────────────────────
    from payments.models import Payment
    stripe_confirmed = Payment.objects.filter(status='succeeded').aggregate(
        t=Sum('amount'))['t'] or 0
    stripe_count = Payment.objects.filter(status='succeeded').count()
    stripe_live = bool(settings.STRIPE_SECRET_KEY and
                       settings.STRIPE_SECRET_KEY.startswith(('sk_live', 'rk_live')))

    # ── Contacts ───────────────────────────────────────────────────────────────
    from clients.models import ContactParent
    contacts_unregistered = ContactParent.objects.filter(client__isnull=True).count()

    context = {
        'today': today,
        # Core counts
        'total_coaches': total_coaches,
        'total_clients': total_clients,
        'total_players': total_players,
        'pending_approvals': pending_approvals,
        # Today
        'todays_bookings': todays_bookings,
        'total_sessions_today': total_sessions_today,
        'pending_bookings': pending_bookings,
        # Financial
        'revenue_this_month': revenue_this_month,
        'revenue_ytd': revenue_ytd,
        'revenue_last_month': revenue_last_month,
        'pending_payments': pending_payments,
        'pending_payments_list': pending_payments_qs[:20],
        'rental_revenue_month': rental_revenue_month,
        'recent_transactions': recent_transactions,
        # Rentals
        'rentals_pending': rentals_pending,
        'rentals_upcoming': rentals_upcoming,
        'rentals_today': rentals_today,
        # Waivers
        'waiver_signed_count': waiver_signed_count,
        'waiver_unsigned_count': waiver_unsigned_count,
        'current_year': current_year,
        # Packages
        'active_packages_count': active_packages_count,
        'packages_breakdown': packages_breakdown,
        'expiring_soon_packages': expiring_soon_packages,
        'packages_exhausted': packages_exhausted,
        # Stripe
        'stripe_live': stripe_live,
        'stripe_count': stripe_count,
        'stripe_confirmed': stripe_confirmed,
        # Contacts
        'contacts_unregistered': contacts_unregistered,
        # Lists
        'coaches': coaches,
        'todays_schedule': todays_schedule,
        'recent_bookings': recent_bookings,
        'recent_transactions': recent_transactions,
        'players_pending_assessment': players_pending_assessment,
        'pending_confirmation_list': pending_confirmation_list,
    }
    return render(request, 'owner/dashboard.html', context)


@login_required
@user_passes_test(is_owner)
def owner_upcoming_sessions(request):
    """Upcoming sessions roster — all coaches, grouped by time / age group / session type / coach."""
    import urllib.parse as _urlparse
    from datetime import datetime as _dt
    from collections import OrderedDict
    from coaches.models import ScheduleBlock

    today = timezone.localdate()
    now_dt = timezone.now()
    cutoff_24h = now_dt + timedelta(hours=24)
    cutoff_48h = now_dt + timedelta(hours=48)

    group_by = request.GET.get('group_by', 'time')
    coach_filter = request.GET.get('coach', '')

    qs = Booking.objects.filter(
        scheduled_date__gte=today,
        scheduled_date__lte=today + timedelta(days=7),
        status__in=['pending', 'confirmed'],
    ).select_related('player', 'coach__user', 'session_type').order_by('scheduled_date', 'scheduled_time')

    if coach_filter:
        try:
            qs = qs.filter(coach_id=int(coach_filter))
        except (ValueError, TypeError):
            pass

    # Build block end-time lookup
    block_end_times = {}
    for block in ScheduleBlock.objects.filter(
        date__gte=today,
        date__lte=today + timedelta(days=7),
    ).values('coach_id', 'date', 'start_time', 'end_time', 'location_override'):
        key = (block['coach_id'], block['date'], block['start_time'])
        block_end_times[key] = (block['end_time'], block['location_override'] or '')

    def _gcal_link(date, start, end, title, location=''):
        fmt = '%Y%m%dT%H%M%S'
        s = _dt.combine(date, start).strftime(fmt)
        e = _dt.combine(date, end).strftime(fmt)
        return 'https://calendar.google.com/calendar/render?' + _urlparse.urlencode({
            'action': 'TEMPLATE', 'text': title,
            'dates': f'{s}/{e}', 'location': location,
        })

    raw_blocks = OrderedDict()
    for bk in qs:
        key = (bk.coach_id, bk.scheduled_date, bk.scheduled_time)
        if key not in raw_blocks:
            end_info = block_end_times.get(key, (None, ''))
            end_t = end_info[0]
            location = end_info[1]
            stype_name = bk.session_type.name if bk.session_type else 'Session'
            coach_name = bk.coach.user.get_full_name() if bk.coach else ''
            raw_blocks[key] = {
                'date': bk.scheduled_date,
                'start_time': bk.scheduled_time,
                'end_time': end_t,
                'session_type_name': stype_name,
                'session_type': bk.session_type,
                'location': location,
                'coach_name': coach_name,
                'coach_id': bk.coach_id,
                'players': [],
                'gcal_link': _gcal_link(
                    bk.scheduled_date, bk.scheduled_time,
                    end_t or bk.scheduled_time,
                    f'APC – {stype_name}', location
                ),
            }
        player = bk.player
        if player:
            raw_blocks[key]['players'].append({
                'name': f'{player.first_name} {player.last_name}',
                'skill_level': player.skill_level or '',
                'age_group': player.age_group if hasattr(player, 'age_group') else '',
                'status': bk.status,
            })

    _age_order = ['U6','U8','U10','U12','U13','U14','U16','U19','Adult','Unknown']
    _skill_order = {'elite': 0, 'advanced': 1, 'intermediate': 2, 'beginner': 3, '': 4}
    for blk in raw_blocks.values():
        by_age = {}
        for p in blk['players']:
            ag = p['age_group'] or 'Unknown'
            by_age.setdefault(ag, []).append(p)
        for ag in by_age:
            by_age[ag].sort(key=lambda p: _skill_order.get(p['skill_level'], 4))
        blk['players_by_age'] = [
            {'age_group': ag, 'players': by_age[ag]}
            for ag in _age_order if ag in by_age
        ] + [
            {'age_group': ag, 'players': by_age[ag]}
            for ag in by_age if ag not in _age_order
        ]

    all_blocks = list(raw_blocks.values())

    def _block_dt(blk):
        naive = _dt.combine(blk['date'], blk['start_time'])
        return timezone.make_aware(naive) if timezone.is_naive(naive) else naive

    if group_by == 'age_group':
        grouped = OrderedDict()
        age_order = ['U6', 'U8', 'U10', 'U12', 'U13', 'U14', 'U16', 'U19', 'Adult']
        for blk in all_blocks:
            ages = list({p['age_group'] for p in blk['players'] if p['age_group']}) or ['Unknown']
            for ag in ages:
                grouped.setdefault(ag, []).append(blk)
        sorted_grouped = OrderedDict()
        for ag in age_order:
            if ag in grouped:
                sorted_grouped[ag] = grouped[ag]
        for ag in grouped:
            if ag not in sorted_grouped:
                sorted_grouped[ag] = grouped[ag]
        grouped_sessions = sorted_grouped
    elif group_by == 'session_type':
        grouped = OrderedDict()
        for blk in all_blocks:
            grouped.setdefault(blk['session_type_name'], []).append(blk)
        grouped_sessions = grouped
    elif group_by == 'coach':
        grouped = OrderedDict()
        for blk in all_blocks:
            grouped.setdefault(blk['coach_name'] or 'Unassigned', []).append(blk)
        grouped_sessions = grouped
    else:  # 'time'
        grouped_sessions = OrderedDict()
        grouped_sessions['Next 24 Hours'] = [b for b in all_blocks if _block_dt(b) <= cutoff_24h]
        grouped_sessions['Next 48 Hours'] = [b for b in all_blocks if cutoff_24h < _block_dt(b) <= cutoff_48h]
        grouped_sessions['Next 7 Days'] = [b for b in all_blocks if _block_dt(b) > cutoff_48h]

    from coaches.models import Coach as _Coach
    coaches = _Coach.objects.filter(is_active=True).select_related('user').order_by('user__first_name')

    return render(request, 'owner/upcoming_sessions.html', {
        'grouped_sessions': grouped_sessions,
        'group_by': group_by,
        'coaches': coaches,
        'coach_filter': coach_filter,
        'total_sessions': len(all_blocks),
        'total_players': sum(len(b['players']) for b in all_blocks),
    })
