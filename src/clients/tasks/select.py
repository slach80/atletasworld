"""
Celery tasks for APC Select program.
"""
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


@shared_task(name='clients.tasks.send_game_day_digest')
def send_game_day_digest():
    """Send a 24-hour pre-game attendance digest to owner and creating coach.

    Runs daily at 8 AM via Celery Beat.
    Finds all published SelectGames scheduled for tomorrow and emails the
    attendance summary (coming / not coming / no response) to the creator and coach.
    """
    from bookings.models import SelectGame
    from django.core.mail import send_mail
    from django.conf import settings as _s
    from django.db.models import Count, Q

    tomorrow = timezone.localdate() + timedelta(days=1)
    games = SelectGame.objects.filter(
        date=tomorrow,
        status='published',
    ).select_related('team', 'created_by', 'coach__user').prefetch_related(
        'rsvps__client__user', 'rsvps__player'
    ).annotate(
        coming_count=Count('rsvps', filter=Q(rsvps__status='coming')),
        not_coming_count=Count('rsvps', filter=Q(rsvps__status='not_coming')),
        pending_count=Count('rsvps', filter=Q(rsvps__status='pending')),
    )

    if not games:
        return 'No games tomorrow'

    sent = 0
    for game in games:
        # Build roster text
        lines = [
            f'APC Select Game — {game.team.name}',
            f'{game.date.strftime("%A, %B %-d, %Y")} at {game.start_time.strftime("%-I:%M %p")}',
            f'Location: {game.location}',
            '',
            f'✅ Coming: {game.coming_count}',
            f'❌ Not Coming: {game.not_coming_count}',
            f'⏳ No Response: {game.pending_count}',
            '',
        ]
        coming_rsvps = [r for r in game.rsvps.all() if r.status == 'coming']
        if coming_rsvps:
            lines.append('CONFIRMED ATTENDANCE:')
            for r in coming_rsvps:
                name = str(r.player) if r.player else str(r.client)
                lines.append(f'  • {name}')

        not_coming_rsvps = [r for r in game.rsvps.all() if r.status == 'not_coming']
        if not_coming_rsvps:
            lines.append('')
            lines.append('NOT COMING:')
            for r in not_coming_rsvps:
                name = str(r.player) if r.player else str(r.client)
                lines.append(f'  • {name}')

        body = '\n'.join(lines)
        subject = f'[APC Select] Game Day Tomorrow — {game.team.name}'
        from_email = getattr(_s, 'DEFAULT_FROM_EMAIL', 'noreply@atletasperformancecenter.com')

        recipients = []
        if game.created_by and game.created_by.email:
            recipients.append(game.created_by.email)
        if game.coach and game.coach.user.email and game.coach.user.email not in recipients:
            recipients.append(game.coach.user.email)
        # Also notify all Owner group users
        from django.contrib.auth.models import User
        for owner in User.objects.filter(groups__name='Owner', is_active=True):
            if owner.email and owner.email not in recipients:
                recipients.append(owner.email)

        if recipients and getattr(_s, 'PRODUCTION_EMAIL_ENABLED', False):
            try:
                send_mail(subject, body, from_email, recipients, fail_silently=True)
                sent += 1
            except Exception as e:
                logger.error('send_game_day_digest: email failed for game %s: %s', game.pk, e)
        else:
            logger.info('send_game_day_digest (dev): game %s — %s', game.pk, body[:120])

    return f'Game day digest sent for {sent}/{len(games)} games'
