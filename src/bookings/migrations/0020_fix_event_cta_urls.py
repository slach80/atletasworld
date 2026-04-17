from django.db import migrations


def fix_event_cta_urls(apps, schema_editor):
    """Replace absolute /#programs and /programs# carousel CTA URLs with /programs/."""
    SessionType = apps.get_model('bookings', 'SessionType')
    bad_suffixes = ['/#programs', '#programs']
    for st in SessionType.objects.exclude(event_cta_url=''):
        url = st.event_cta_url
        changed = False
        for suffix in bad_suffixes:
            if url.endswith(suffix):
                st.event_cta_url = '/programs/'
                changed = True
                break
        if changed:
            st.save(update_fields=['event_cta_url'])


class Migration(migrations.Migration):
    dependencies = [
        ('bookings', '0019_merge_20260413_1657'),
    ]

    operations = [
        migrations.RunPython(fix_event_cta_urls, migrations.RunPython.noop),
    ]
