from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0017_add_performance_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='sessiontype',
            name='day_capacities',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Per-day/time capacity overrides e.g. {"Mon_17:00": 20, "Sat_15:00": 40}',
            ),
        ),
    ]
