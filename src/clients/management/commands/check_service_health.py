"""
Management command: check Celery worker + beat health and alert by email
if scheduled tasks aren't actually firing.

Deliberately does NOT run as a Celery Beat task — the failure this exists
to catch is beat itself being down (as happened for months: the
supervisor program for `celery beat` was never created, so every entry
in `celery.py`'s beat_schedule silently never fired). A beat-scheduled
health check shares the exact same blind spot. Run this from real OS
cron instead, independent of Celery entirely.

Usage:
    python manage.py check_service_health
"""
import datetime

from django.core.cache import caches
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

ALERT_RECIPIENT = 'info@atletasperformancecenter.com'
GRACE = datetime.timedelta(hours=2)
# How often to re-send an alert for the *same* still-unresolved issue.
# Cron runs this every 30 min — without a cooldown, a single stuck task
# emails every 30 min for as long as it stays broken.
ALERT_COOLDOWN = datetime.timedelta(hours=4)
CACHE_KEY = 'health_check:last_alert_signature'


class Command(BaseCommand):
    help = "Check that Celery Beat is actually ticking and workers are reachable; email an alert if not."

    def handle(self, *args, **options):
        # (stable_key, human_readable_message) — key is used for dedup,
        # since the message includes an exact overdue duration that
        # changes every run and would defeat any cooldown.
        issues = []
        issues += self._check_beat_schedule()
        issues += self._check_worker_reachable()

        cache = caches['vald']  # Redis-backed; survives across cron's fresh processes

        if not issues:
            cache.delete(CACHE_KEY)
            self.stdout.write(self.style.SUCCESS("Background tasks healthy"))
            return

        signature = '|'.join(sorted(key for key, _ in issues))
        last = cache.get(CACHE_KEY)
        if last and last['signature'] == signature and \
                timezone.now() - last['sent_at'] < ALERT_COOLDOWN:
            self.stdout.write(self.style.WARNING(
                f"{len(issues)} issue(s) still present, alert suppressed "
                f"(cooldown, last sent {last['sent_at']:%Y-%m-%d %H:%M})"
            ))
            for _, message in issues:
                self.stdout.write(f"  - {message}")
            return

        body = (
            "⚠️ Background Task Health Alert — Atletas Performance Center\n\n"
            + "\n".join(f"• {message}" for _, message in issues)
            + "\n\nCheck `sudo supervisorctl status` on the EC2 box — "
              "atletasworld-celery and atletasworld-celery-beat must both be RUNNING."
              f"\n\n(You won't get another email for this same issue for {ALERT_COOLDOWN}, "
              "unless it changes or clears and comes back.)\n"
        )
        send_mail(
            subject='⚠️ Background Task Health Issue — APC',
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[ALERT_RECIPIENT],
            fail_silently=False,
        )
        cache.set(CACHE_KEY, {'signature': signature, 'sent_at': timezone.now()},
                   timeout=int(ALERT_COOLDOWN.total_seconds()) * 2)
        self.stdout.write(self.style.ERROR(f"Alert sent — {len(issues)} issue(s):"))
        for _, message in issues:
            self.stdout.write(f"  - {message}")

    def _check_beat_schedule(self):
        from django_celery_beat.models import PeriodicTask

        issues = []
        tasks = PeriodicTask.objects.filter(enabled=True).exclude(task='celery.backend_cleanup')
        for task in tasks:
            schedule = task.schedule
            if schedule is None or not hasattr(schedule, 'remaining_estimate'):
                continue
            baseline = task.last_run_at or task.date_changed
            remaining = schedule.remaining_estimate(baseline)
            if remaining is not None and remaining < -GRACE:
                last_run = task.last_run_at.isoformat() if task.last_run_at else 'never'
                overdue_by = -remaining - GRACE
                issues.append((
                    f'beat_overdue:{task.name}',
                    f"'{task.name}' ({task.task}) is overdue by {overdue_by} — last run: {last_run}",
                ))
        return issues

    def _check_worker_reachable(self):
        from celery import current_app

        try:
            pings = current_app.control.ping(timeout=3)
        except Exception as e:
            return [('worker_unreachable', f"Could not reach the Celery broker to ping workers: {e}")]

        if not pings:
            return [('worker_down', "No Celery workers responded to ping — the worker process may be down.")]
        return []
