"""
Set location_override on Summer Program schedule blocks based on day/time pattern:
- Mon/Wed/Sat/Sun → APC Indoor Facility
- Tue/Thu before 12pm → Hocker Grove Middle School
- Tue/Thu 12pm+ → Shawnee Mission North HS
"""
from django.db import migrations
from datetime import time


def set_locations(apps, schema_editor):
    ScheduleBlock = apps.get_model('coaches', 'ScheduleBlock')
    SessionType = apps.get_model('bookings', 'SessionType')

    summer_types = SessionType.objects.filter(
        name__icontains='summer program', is_active=True
    )
    if not summer_types.exists():
        return

    summer_type_ids = list(summer_types.values_list('id', flat=True))

    blocks = ScheduleBlock.objects.filter(
        catalog_session_types__id__in=summer_type_ids,
        status='available',
    ).distinct()

    for block in blocks:
        dow = block.date.weekday()  # 0=Mon, 1=Tue, ..., 6=Sun

        if dow in (0, 2, 5, 6):  # Mon, Wed, Sat, Sun
            block.location_override = 'APC Indoor Facility'
        elif dow in (1, 3):  # Tue, Thu
            if block.start_time < time(12, 0):
                block.location_override = 'Hocker Grove Middle School'
            else:
                block.location_override = 'Shawnee Mission North HS'
        elif dow == 4:  # Fri
            block.location_override = 'APC Indoor Facility'

        block.save(update_fields=['location_override'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0036_merge_0034_0035'),
        ('coaches', '0010_create_summer_program_schedule_blocks'),
    ]

    operations = [
        migrations.RunPython(set_locations, noop),
    ]
