"""Add 'tournament' session format and APC 4x4 FIFA Tournament event."""

from django.db import migrations, models


def create_fifa_tournament(apps, schema_editor):
    SessionType = apps.get_model('bookings', 'SessionType')
    SessionType.objects.create(
        name='APC 4x4 FIFA Tournament',
        description=(
            'APC\'s 4x4 on-field tournament brings our community together for a '
            'fun, competitive event — open to players, parents, and fans. '
            'Small-sided 4v4 format on the APC pitch. Prizes for top finishers.'
        ),
        session_format='tournament',
        duration_minutes=180,
        price=0,
        max_participants=32,
        color='#f59e0b',       # amber
        is_active=True,
        requires_package=False,
        allow_package=False,
        show_as_event=True,
        show_as_program=False,
        location='Atletas Performance Center',
        age_group='All ages',
        event_cta_text='Get Notified',
        event_cta_url='mailto:info@atletasperformancecenter.com?subject=APC 4x4 FIFA Tournament — Notify Me',
        event_display_order=5,
    )


def remove_fifa_tournament(apps, schema_editor):
    SessionType = apps.get_model('bookings', 'SessionType')
    SessionType.objects.filter(name='APC 4x4 FIFA Tournament').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0019_merge_20260413_1657'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sessiontype',
            name='session_format',
            field=models.CharField(
                choices=[
                    ('private', 'Private (1-on-1)'),
                    ('semi_private', 'Semi-Private (2-3 players)'),
                    ('group', 'Group Session'),
                    ('team', 'Team Training'),
                    ('clinic', 'Clinic'),
                    ('camp', 'Camp'),
                    ('seasonal', 'Seasonal Package'),
                    ('pickup', 'Pick Up Game'),
                    ('tryout', 'Tryout'),
                    ('tournament', 'Tournament'),
                ],
                default='private',
                max_length=20,
            ),
        ),
        migrations.RunPython(create_fifa_tournament, remove_fifa_tournament),
    ]
