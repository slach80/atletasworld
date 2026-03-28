"""
Signals for the clients app.
Auto-adds users to Client group on signup.
"""
from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver
from allauth.account.signals import user_signed_up


@receiver(user_signed_up)
def add_user_to_client_group(sender, request, user, **kwargs):
    """
    Add newly signed up users to the Client group.
    Coach accounts are created by admin and added to Coach group manually.
    """
    client_group, created = Group.objects.get_or_create(name='Client')
    user.groups.add(client_group)
