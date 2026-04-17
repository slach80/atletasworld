import os
import shutil
from django.db import migrations
from django.conf import settings


SLUG_TO_STATIC = {
    'mirko': 'img/mirko.jpg',
    'roger': 'img/roger.jpg',
}


def copy_photos(apps, schema_editor):
    Coach = apps.get_model('coaches', 'Coach')
    dest_dir = os.path.join(settings.MEDIA_ROOT, 'coaches')
    os.makedirs(dest_dir, exist_ok=True)

    for slug, static_rel in SLUG_TO_STATIC.items():
        coach = Coach.objects.filter(slug=slug).first()
        if coach is None or coach.photo:
            continue

        src = os.path.join(settings.BASE_DIR, '..', 'static', static_rel)
        src = os.path.normpath(src)
        if not os.path.exists(src):
            continue

        filename = f'{slug}.jpg'
        dest = os.path.join(dest_dir, filename)
        shutil.copy2(src, dest)
        coach.photo = f'coaches/{filename}'
        coach.save(update_fields=['photo'])


def remove_photos(apps, schema_editor):
    Coach = apps.get_model('coaches', 'Coach')
    for slug in SLUG_TO_STATIC:
        Coach.objects.filter(slug=slug).update(photo='')


class Migration(migrations.Migration):
    dependencies = [
        ('coaches', '0014_seed_sessions_display_floor'),
    ]

    operations = [
        migrations.RunPython(copy_photos, remove_photos),
    ]
