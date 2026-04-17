from django.db import migrations


def seed_sessions_display_floor(apps, schema_editor):
    Coach = apps.get_model('coaches', 'Coach')
    floors = {'mirko': 1000, 'roger': 800}
    for slug, floor in floors.items():
        Coach.objects.filter(slug=slug).update(sessions_display_floor=floor)


class Migration(migrations.Migration):
    dependencies = [
        ('coaches', '0013_add_sessions_display_floor'),
    ]

    operations = [
        migrations.RunPython(seed_sessions_display_floor, migrations.RunPython.noop),
    ]
