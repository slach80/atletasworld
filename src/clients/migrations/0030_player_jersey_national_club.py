from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0029_notification_outbox'),
    ]

    operations = [
        migrations.AddField(
            model_name='player',
            name='jersey_size',
            field=models.CharField(
                blank=True, max_length=10,
                choices=[
                    ('', '-- Select Size --'),
                    ('youth_s', 'Youth S'), ('youth_m', 'Youth M'),
                    ('youth_l', 'Youth L'), ('youth_xl', 'Youth XL'),
                    ('adult_s', 'Adult S'), ('adult_m', 'Adult M'),
                    ('adult_l', 'Adult L'), ('adult_xl', 'Adult XL'),
                ],
                help_text='Shirt/jersey size for kits and team gear',
            ),
        ),
        migrations.AddField(
            model_name='player',
            name='favorite_national_team',
            field=models.CharField(
                blank=True, max_length=20,
                choices=[
                    ('', '-- Select Team --'),
                    ('usa', 'USA'), ('brazil', 'Brazil'), ('italy', 'Italy'),
                    ('argentina', 'Argentina'), ('england', 'England'),
                    ('spain', 'Spain'), ('colombia', 'Colombia'),
                    ('honduras', 'Honduras'), ('mexico', 'Mexico'),
                    ('netherlands', 'Netherlands'), ('germany', 'Germany'),
                    ('france', 'France'), ('portugal', 'Portugal'),
                    ('serbia', 'Serbia'), ('senegal', 'Senegal'), ('ghana', 'Ghana'),
                ],
                help_text="Player's favorite national team",
            ),
        ),
        migrations.AddField(
            model_name='player',
            name='favorite_club_team',
            field=models.CharField(
                blank=True, max_length=100,
                help_text="Player's favorite club team (e.g. PSG, LFC, Real Madrid)",
            ),
        ),
    ]
