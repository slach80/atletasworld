from django.db import migrations
from decimal import Decimal


def seed_select_teams(apps, schema_editor):
    Team = apps.get_model('clients', 'Team')
    # Mark existing 2014/2015/2016 APC Select teams
    for year in [2014, 2015, 2016]:
        Team.objects.filter(name__icontains=str(year)).update(is_select=True)


def create_select_session_types(apps, schema_editor):
    SessionType = apps.get_model('bookings', 'SessionType')

    SessionType.objects.get_or_create(
        name='APC Select Practice',
        defaults={
            'session_format': 'select_practice',
            'duration_minutes': 60,
            'price': Decimal('0.00'),
            'drop_in_price': Decimal('0.00'),
            'max_participants': 15,
            'requires_package': False,
            'allow_package': True,
            'is_active': True,
            'color': '#6366f1',
        },
    )

    SessionType.objects.get_or_create(
        name='APC Select Game',
        defaults={
            'session_format': 'select_game',
            'duration_minutes': 60,
            'price': Decimal('0.00'),
            'drop_in_price': Decimal('0.00'),
            'max_participants': 30,
            'requires_package': False,
            'allow_package': False,
            'is_active': True,
            'color': '#a855f7',
        },
    )


def reverse_select_teams(apps, schema_editor):
    Team = apps.get_model('clients', 'Team')
    Team.objects.filter(is_select=True).update(is_select=False)


def reverse_session_types(apps, schema_editor):
    SessionType = apps.get_model('bookings', 'SessionType')
    SessionType.objects.filter(
        name__in=['APC Select Practice', 'APC Select Game']
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0040_select_team_flag_and_player_select_teams_and_billing_tier'),
        ('bookings', '0022_add_select_formats_and_select_game_models'),
    ]

    operations = [
        migrations.RunPython(seed_select_teams, reverse_select_teams),
        migrations.RunPython(create_select_session_types, reverse_session_types),
    ]
