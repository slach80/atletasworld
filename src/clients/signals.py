"""
Signals for the clients app.
Auto-adds users to Client group on signup.
"""
from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from allauth.account.signals import user_signed_up, password_changed, password_reset


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


@receiver(password_changed)
@receiver(password_reset)
def update_password_expiry(sender, request, user, **kwargs):
    """Reset the password expiry clock whenever a user changes or resets their password."""
    from clients.models import UserPasswordExpiry
    UserPasswordExpiry.objects.update_or_create(
        user=user,
        defaults={'password_changed_at': timezone.now()}
    )


@receiver(post_save, sender='auth.User')
def generate_referral_code(sender, instance, created, **kwargs):
    """
    Auto-generate a unique referral code for every new user.

    Code format: 8-character uppercase alphanumeric (e.g., 'AB3XZ8K9').
    For existing users, codes are generated on-demand when they visit the referral page.
    """
    if not created:
        return

    from clients.models import ReferralCode
    import secrets

    # Generate unique code
    while True:
        code = secrets.token_urlsafe(6).upper().replace('-', '').replace('_', '')[:8]
        if not ReferralCode.objects.filter(code=code).exists():
            break

    ReferralCode.objects.create(user=instance, code=code)


@receiver(user_signed_up)
def track_referral_on_signup(sender, request, user, **kwargs):
    """
    Track referral relationship when a new user signs up with a referral code.

    The code can come from:
    1. Session (captured by ReferralCodeMiddleware from ?ref=CODE URL param)
    2. Form field (if added to signup template)

    Creates a pending Referral record with 60-day window for first purchase.
    """
    from clients.models import ReferralCode, Referral
    from datetime import timedelta

    # Check session first (from middleware)
    ref_code = request.session.pop('referral_code', None)

    # Fallback to form field
    if not ref_code:
        ref_code = request.POST.get('referral_code', '').strip().upper()

    if not ref_code:
        return

    # Look up referrer by code
    try:
        referrer_code = ReferralCode.objects.select_related('user').get(code=ref_code)
    except ReferralCode.DoesNotExist:
        return

    # Prevent self-referral
    if referrer_code.user == user:
        return

    # Determine referrer type (client vs coach)
    is_coach = referrer_code.user.groups.filter(name='Coach').exists()
    referrer_type = 'coach' if is_coach else 'client'

    # Create pending referral with 60-day window
    Referral.objects.create(
        referrer_user=referrer_code.user,
        referred_user=user,
        referral_code=ref_code,
        referrer_type=referrer_type,
        status='pending',
        referral_window_expires=timezone.now() + timedelta(days=60),
    )
