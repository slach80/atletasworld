#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'atletasworld.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/src')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

# Reset owner password
try:
    owner = User.objects.get(email='owner@atletasworld.com')
    owner.set_password('owner123')
    owner.save()
    print(f'✅ Owner account updated: owner@atletasworld.com / owner123')
except User.DoesNotExist:
    print('❌ Owner user not found')

# Check all owners
print('\n=== OWNER ACCOUNTS ===')
owners = User.objects.filter(groups__name='Owner')
for user in owners:
    print(f'{user.email} - {user.get_full_name()}')
