from django.db import migrations


def register_game_day_digest(apps, schema_editor):
    try:
        from django_celery_beat.models import PeriodicTask, CrontabSchedule
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='8',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )
        PeriodicTask.objects.get_or_create(
            name='Send Select game day digest',
            defaults={
                'task': 'clients.tasks.send_game_day_digest',
                'crontab': schedule,
                'enabled': True,
            },
        )
    except Exception:
        pass  # django_celery_beat may not be installed in all environments


def reverse_game_day_digest(apps, schema_editor):
    try:
        from django_celery_beat.models import PeriodicTask
        PeriodicTask.objects.filter(name='Send Select game day digest').delete()
    except Exception:
        pass


class Migration(migrations.Migration):
    # Must run outside a transaction: imports live django_celery_beat models
    # which can trigger SQL errors that abort a Postgres transaction block,
    # poisoning the connection for all subsequent test DB setup.
    atomic = False

    dependencies = [
        ('clients', '0041_seed_select_teams_and_session_types'),
    ]

    operations = [
        migrations.RunPython(register_game_day_digest, reverse_game_day_digest),
    ]
