#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'atletasworld.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.contrib.auth.models import Group, User

print('=== USER GROUPS ===')
for group in Group.objects.all():
    print(f'{group.name}: {group.user_set.count()} users')

print('\n=== ALL USERS ===')
for user in User.objects.all():
    groups = ', '.join([g.name for g in user.groups.all()]) or 'No group'
    print(f'{user.username} ({user.email}): {groups}')
