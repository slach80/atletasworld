from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Change favorite_national_team from a restricted choice field (16 options)
    to a free-text CharField so all 211 FIFA member nations can be stored.
    The datalist in the form template provides searchable autocomplete.
    """

    dependencies = [
        ('clients', '0030_player_jersey_national_club'),
    ]

    operations = [
        migrations.AlterField(
            model_name='player',
            name='favorite_national_team',
            field=models.CharField(
                blank=True,
                max_length=100,
                help_text='Player\'s favorite national team (free text + autocomplete from full FIFA list)',
            ),
        ),
    ]
