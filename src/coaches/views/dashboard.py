from django.shortcuts import render
from django.utils import timezone
from django.db.models import Avg
from datetime import timedelta
from coaches.models import Coach, ScheduleBlock
from bookings.models import Booking
from ._auth import coach_required


@coach_required
def dashboard(request):
    """Coach dashboard with overview."""
    coach = request.coach
    today = timezone.localdate()

    # Today's sessions — blocks with at least one booking
    todays_blocks = ScheduleBlock.objects.filter(
        coach=coach,
        date=today,
        current_participants__gt=0
    ).prefetch_related('attendances__booking__player')

    # Upcoming sessions (next 30 days) — blocks with at least one booking
    upcoming_blocks = ScheduleBlock.objects.filter(
        coach=coach,
        date__gt=today,
        date__lte=today + timedelta(days=30),
        current_participants__gt=0
    ).order_by('date', 'start_time')[:10]

    # Pending assessments (sessions completed but not assessed)
    pending_assessments = Booking.objects.filter(
        coach=coach,
        status='completed',
        scheduled_date__gte=today - timedelta(days=7)
    ).exclude(
        assessments__isnull=False
    ).select_related('player', 'session_type')[:10]

    # Stats
    week_start   = today - timedelta(days=today.weekday())
    week_end     = week_start + timedelta(days=6)
    month_start  = today.replace(day=1)
    sessions_this_month = Booking.objects.filter(
        coach=coach,
        scheduled_date__gte=month_start,
        scheduled_date__lte=today,
        status__in=['confirmed', 'completed'],
    ).count()
    stats = {
        'students_this_week': Booking.objects.filter(
            coach=coach,
            scheduled_date__gte=week_start,
            scheduled_date__lte=week_end,
            status__in=['pending', 'confirmed'],
        ).values('player').distinct().count(),
        'sessions_this_month': sessions_this_month,
        'upcoming_sessions': upcoming_blocks.count(),
        'pending_assessments': pending_assessments.count(),
    }

    # Upcoming session roster — built once, regrouped client-side (no page reload)
    import json as _json
    import urllib.parse as _urlparse
    from datetime import datetime as _dt

    upcoming_bookings = Booking.objects.filter(
        coach=coach,
        scheduled_date__gte=today,
        scheduled_date__lte=today + timedelta(days=7),
        status__in=['pending', 'confirmed'],
    ).select_related('player', 'session_type').order_by('scheduled_date', 'scheduled_time')

    block_end_times = {}
    for block in ScheduleBlock.objects.filter(
        coach=coach,
        date__gte=today,
        date__lte=today + timedelta(days=7),
    ).values('date', 'start_time', 'end_time', 'location_override'):
        key = (block['date'], block['start_time'])
        block_end_times[key] = (block['end_time'], block['location_override'])

    def _gcal_link(date, start, end, title, location=''):
        fmt = '%Y%m%dT%H%M%S'
        s = _dt.combine(date, start).strftime(fmt)
        e = _dt.combine(date, end).strftime(fmt)
        return 'https://calendar.google.com/calendar/render?' + _urlparse.urlencode({
            'action': 'TEMPLATE', 'text': title,
            'dates': f'{s}/{e}', 'location': location,
        })

    raw_blocks: dict = {}
    raw_blocks_order: list = []
    for bk in upcoming_bookings:
        key = (str(bk.scheduled_date), str(bk.scheduled_time))
        if key not in raw_blocks:
            end_time_info = block_end_times.get((bk.scheduled_date, bk.scheduled_time), (None, ''))
            end_t = end_time_info[0]
            location = end_time_info[1] or ''
            stype_name = bk.session_type.name if bk.session_type else 'Session'
            raw_blocks[key] = {
                'date': str(bk.scheduled_date),
                'date_display': bk.scheduled_date.strftime('%a, %b %-d'),
                'start_time': str(bk.scheduled_time),
                'start_display': bk.scheduled_time.strftime('%-I:%M %p'),
                'end_display': end_t.strftime('%-I:%M %p') if end_t else '',
                'session_type_name': stype_name,
                'location': location,
                'gcal_link': _gcal_link(
                    bk.scheduled_date, bk.scheduled_time,
                    end_t or bk.scheduled_time,
                    f'APC – {stype_name}', location
                ),
                'players': [],
                # ISO datetime string for client-side time bucketing
                'iso_dt': _dt.combine(bk.scheduled_date, bk.scheduled_time).isoformat(),
            }
            raw_blocks_order.append(key)
        player = bk.player
        if player:
            raw_blocks[key]['players'].append({
                'name': f'{player.first_name} {player.last_name}',
                'skill_level': player.skill_level or '',
                'age_group': player.age_group if hasattr(player, 'age_group') else '',
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

    roster_blocks_json = _json.dumps([raw_blocks[k] for k in raw_blocks_order])

    # Coach rating
    from reviews.models import Review
    from django.db.models import Avg
    coach_rating = None
    coach_review_count = 0
    if coach.profile_enabled:
        review_agg = Review.objects.filter(coach=coach, is_approved=True).aggregate(
            avg=Avg('rating'), count=__import__('django.db.models', fromlist=['Count']).Count('id')
        )
        coach_rating      = round(review_agg['avg'], 1) if review_agg['avg'] else None
        coach_review_count= review_agg['count'] or 0

    # Teams this coach is assigned to
    teams = coach.teams.filter(is_active=True)

    # "Starts soon" — blocks starting within 2 hours
    now_dt = timezone.now()
    starts_soon = {}
    for block in todays_blocks:
        import datetime as dt
        block_dt = dt.datetime.combine(today, block.start_time)
        block_dt = timezone.make_aware(block_dt) if timezone.is_naive(block_dt) else block_dt
        mins = int((block_dt - now_dt).total_seconds() / 60)
        if 0 < mins <= 120:
            starts_soon[block.id] = mins

    context = {
        'coach': coach,
        'todays_blocks': todays_blocks,
        'roster_blocks_json': roster_blocks_json,
        'upcoming_blocks': upcoming_blocks,
        'pending_assessments': pending_assessments,
        'stats': stats,
        'today': today,
        'teams': teams,
        'coach_rating': coach_rating,
        'coach_review_count': coach_review_count,
        'starts_soon': starts_soon,
    }
    return render(request, 'coaches/dashboard.html', context)
