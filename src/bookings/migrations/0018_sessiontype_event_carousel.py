from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0017_add_performance_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='sessiontype',
            name='poster_image',
            field=models.ImageField(
                blank=True, null=True, upload_to='events/',
                help_text="Optional poster image — fills the card. If set, text details are hidden."
            ),
        ),
        migrations.AddField(
            model_name='sessiontype',
            name='event_cta_text',
            field=models.CharField(
                blank=True, max_length=80,
                help_text="Button label, e.g. 'Learn More →'. Leave blank to hide button."
            ),
        ),
        migrations.AddField(
            model_name='sessiontype',
            name='event_cta_url',
            field=models.CharField(
                blank=True, max_length=200,
                help_text="Button destination URL (e.g. /programs/)."
            ),
        ),
        migrations.AddField(
            model_name='sessiontype',
            name='event_display_order',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Lower numbers appear first in the carousel."
            ),
        ),
    ]
