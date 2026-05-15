from django.db import migrations


class Migration(migrations.Migration):
    """No-op: ordering/indexes/constraints for referral models already exist in production.
    This migration was auto-generated on production — kept empty to satisfy the graph."""

    dependencies = [
        ('clients', '0033_referral_program'),
    ]

    operations = []
