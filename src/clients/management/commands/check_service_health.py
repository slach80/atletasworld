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

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

ALERT_RECIPIENT = 'info@atletasperformancecenter.com'
GRACE = datetime.timedelta(hours=2)


class Command(BaseCommand):
    help = "Check that Celery Beat is actually ticking and workers are reachable; email an alert if not."

    def handle(self, *args, **options):
        issues = []
        issues += self._check_beat_schedule()
        issues += self._check_worker_reachable()

        if issues:
            body = (
                "⚠️ Background Task Health Alert — Atletas Performance Center\n\n"
                + "\n".join(f"• {issue}" for issue in issues)
                + "\n\nCheck `sudo supervisorctl status` on the EC2 box — "
                  "atletasworld-celery and atletasworld-celery-beat must both be RUNNING.\n"
            )
            send_mail(
                subject='⚠️ Background Task Health Issue — APC',
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[ALERT_RECIPIENT],
                fail_silently=False,
            )
            self.stdout.write(self.style.ERROR(f"Alert sent — {len(issues)} issue(s):"))
            for issue in issues:
                self.stdout.write(f"  - {issue}")
        else:
            self.stdout.write(self.style.SUCCESS("Background tasks healthy"))

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
                issues.append(
                    f"'{task.name}' ({task.task}) is overdue by {overdue_by} — last run: {last_run}"
                )
        return issues

    def _check_worker_reachable(self):
        from celery import current_app

        try:
            pings = current_app.control.ping(timeout=3)
        except Exception as e:
            return [f"Could not reach the Celery broker to ping workers: {e}"]

        if not pings:
            return ["No Celery workers responded to ping — the worker process may be down."]
        return []
