from django.db import migrations


class Migration(migrations.Migration):
    """No-op: the referral FK on ClientCredit is already added by 0033_referral_program.
    This migration existed on production only — kept as empty to satisfy the migration graph."""

    dependencies = [
        ('clients', '0033_referral_program'),
    ]

    operations = []
