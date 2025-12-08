"""
Data migration to create Coach and Client user groups.
"""
from django.db import migrations


def create_user_groups(apps, schema_editor):
    """Create Coach and Client user groups."""
    Group = apps.get_model('auth', 'Group')
    
    # Create groups
    Group.objects.get_or_create(name='Coach')
    Group.objects.get_or_create(name='Client')


def remove_user_groups(apps, schema_editor):
    """Remove Coach and Client user groups."""
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=['Coach', 'Client']).delete()


class Migration(migrations.Migration):
    
    dependencies = [
        ('clients', '0006_add_special_package_fields'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(create_user_groups, remove_user_groups),
    ]
