from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0031_player_national_team_free_text'),
    ]

    operations = [
        migrations.CreateModel(
            name='UnsubscribeToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, max_length=64, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('client', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='unsubscribe_token',
                    to='clients.client',
                )),
            ],
        ),
    ]
