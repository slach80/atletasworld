from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0033_referral_program'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientcredit',
            name='referral',
            field=models.ForeignKey(
                blank=True,
                help_text='The Referral that generated this credit',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='credits',
                to='clients.referral',
            ),
        ),
    ]
