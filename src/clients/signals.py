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


@receiver(user_signed_up)
def link_contact_import_on_signup(sender, request, user, **kwargs):
    """
    When a new user signs up, check if their email matches a ContactParent.
    If found, link the contact → client so the owner can see the history.
    """
    from django.utils import timezone as tz
    from clients.models import ContactParent, Client
    if not user.email:
        return
    contact = ContactParent.objects.filter(
        email__iexact=user.email.strip(),
        client__isnull=True,
    ).first()
    if not contact:
        return
    # Get or create the Client profile for this user
    client, _ = Client.objects.get_or_create(user=user)
    contact.client    = client
    contact.linked_at = tz.now()
    contact.save(update_fields=['client', 'linked_at'])
