from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0028_seed_password_expiry'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationOutbox',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('group_key', models.CharField(max_length=120, unique=True)),
                ('events', models.JSONField(default=list, help_text='Accumulated list of {type, context, ts} dicts')),
                ('send_after', models.DateTimeField(help_text='Task runs after this time')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('client', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='outbox',
                    to='clients.client',
                )),
            ],
            options={
                'indexes': [models.Index(fields=['send_after'], name='clients_not_send_af_idx')],
            },
        ),
    ]
