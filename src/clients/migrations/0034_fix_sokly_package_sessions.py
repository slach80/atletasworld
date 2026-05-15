"""
One-time data fix: restore 2 sessions to Sokly Lach's package that were
incorrectly consumed by the old booking code (Pick-Up Game booked via
package when it should have required payment).
"""
from django.db import migrations


def restore_sessions(apps, schema_editor):
    ClientPackage = apps.get_model('clients', 'ClientPackage')
    Client = apps.get_model('clients', 'Client')
    User = apps.get_model('auth', 'User')
    Package = apps.get_model('clients', 'Package')

    # Find Sokly's user
    user = User.objects.filter(first_name__icontains='sokly').first()
    if not user:
        user = User.objects.filter(email__icontains='sokly').first()
    if not user:
        return

    # Find their client profile
    try:
        client = Client.objects.get(user=user)
    except Client.DoesNotExist:
        return

    # Restore 2 sessions to their active/exhausted session-based package
    packages = ClientPackage.objects.filter(
        client=client,
        status__in=['active', 'exhausted'],
    )

    for pkg in packages:
        # Get the related package to check sessions_included
        try:
            catalog_pkg = Package.objects.get(pk=pkg.package_id)
        except Package.DoesNotExist:
            continue
        if catalog_pkg.sessions_included > 0:
            pkg.sessions_remaining += 2
            pkg.sessions_used = max(0, pkg.sessions_used - 2)
            if pkg.status == 'exhausted':
                pkg.status = 'active'
            pkg.save()
            break


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0033_referral_program'),
    ]

    operations = [
        migrations.RunPython(restore_sessions, noop),
    ]
