"""
Data migration: give all existing users a 6-month grace period.
Sets password_changed_at = now() - 6 months so their password
expires in ~6 months from deployment.
"""
from django.db import migrations
from django.utils import timezone
from datetime import timedelta


def seed_password_expiry(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    UserPasswordExpiry = apps.get_model('clients', 'UserPasswordExpiry')
    grace = timezone.now() - timedelta(days=180)  # 6 months ago → expires in 6 months
    objs = [
        UserPasswordExpiry(user=user, password_changed_at=grace)
        for user in User.objects.all()
        if not UserPasswordExpiry.objects.filter(user=user).exists()
    ]
    UserPasswordExpiry.objects.bulk_create(objs)


def reverse_seed(apps, schema_editor):
    apps.get_model('clients', 'UserPasswordExpiry').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0027_userpasswordexpiry'),
    ]

    operations = [
        migrations.RunPython(seed_password_expiry, reverse_seed),
    ]
