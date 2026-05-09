from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('clients', '0032_add_unsubscribe_token'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReferralCode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, max_length=20, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='referral_code',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='Referral',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('referral_code', models.CharField(db_index=True, max_length=20)),
                ('referrer_type', models.CharField(
                    choices=[('client', 'Client'), ('coach', 'Coach')],
                    max_length=10,
                )),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('activated', 'Activated'), ('expired', 'Expired')],
                    default='pending',
                    max_length=20,
                )),
                ('activated_at', models.DateTimeField(blank=True, null=True)),
                ('activation_purchase_amount', models.DecimalField(
                    blank=True,
                    decimal_places=2,
                    max_digits=8,
                    null=True,
                )),
                ('reward_amount', models.DecimalField(
                    blank=True,
                    decimal_places=2,
                    max_digits=8,
                    null=True,
                )),
                ('referral_window_expires', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('referrer_user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='referrals_given',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('referred_user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='referrals_received',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='ReferralPayout',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=8)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending Review'),
                        ('approved', 'Approved'),
                        ('paid', 'Paid'),
                        ('rejected', 'Rejected'),
                    ],
                    default='pending',
                    max_length=15,
                )),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('rejection_reason', models.TextField(blank=True)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('payment_notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('coach_user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='referral_payouts',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('referral', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='payout',
                    to='clients.referral',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.AddField(
            model_name='clientcredit',
            name='referral',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='credits',
                to='clients.referral',
            ),
        ),
    ]
