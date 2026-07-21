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
    When a new user signs up:
    1. Check if their email matches an existing ContactParent (from CSV import)
       → If found, link it to the new Client profile
    2. If NOT found, create a new ContactParent record so owner's "All Contacts" list grows
    """
    from django.utils import timezone as tz
    from clients.models import ContactParent, Client
    if not user.email:
        return

    # Get or create the Client profile for this user
    client, _ = Client.objects.get_or_create(user=user)

    # Check if this email exists in ContactParent (CSV import)
    contact = ContactParent.objects.filter(
        email__iexact=user.email.strip(),
        client__isnull=True,
    ).first()

    if contact:
        # Link existing ContactParent to new Client
        contact.client = client
        contact.linked_at = tz.now()
        contact.save(update_fields=['client', 'linked_at'])
    else:
        # Create new ContactParent so this signup appears in owner's "All Contacts" list
        ContactParent.objects.get_or_create(
            email=user.email.strip().lower(),
            defaults={
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'source': 'signup',
                'client': client,
                'linked_at': tz.now(),
            }
        )


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

    # Generate unique code (loop until we get 6-8 alphanumeric chars)
    while True:
        raw = secrets.token_urlsafe(8).upper().replace('-', '').replace('_', '')
        code = raw[:8]
        if len(code) >= 6 and not ReferralCode.objects.filter(code=code).exists():
            break

    ReferralCode.objects.create(user=instance, code=code)


@receiver(post_save, sender='clients.ClientPackage')
def seed_select_credits(sender, instance, created, **kwargs):
    """Seed 6×$40 monthly training credits whenever an APC Select package is activated.

    Runs on every save where status becomes 'active', so it covers admin assignments,
    manual creation, and any future path that bypasses the Stripe webhook.
    Guard: skips if the client already has any select_monthly credits from this package
    so it's safe to call multiple times (e.g. status toggled active → inactive → active).
    """
    if instance.status != 'active':
        return
    if instance.package.package_type != 'select':
        return

    from clients.models import ClientCredit
    from decimal import Decimal
    import datetime

    already = ClientCredit.objects.filter(
        client=instance.client,
        credit_type='select_monthly',
        source_package=instance,
    ).exists()
    if already:
        return

    year_end = datetime.date(instance.expiry_date.year, 12, 31)
    for month in range(1, 7):
        ClientCredit.objects.create(
            client=instance.client,
            amount=Decimal('40.00'),
            credit_type='select_monthly',
            source_package=instance,
            expires_at=year_end,
            notes=f'APC Select — Month {month} training credit ($40 toward any APC Training session or package)',
        )


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


@receiver(post_save, sender='bookings.SelectGame')
def fanout_select_game_rsvps(sender, instance, **kwargs):
    """When a SelectGame is published, create RSVP records for all eligible players
    and send them a notification.

    Idempotent: uses get_or_create so re-publishing or re-saving is safe.
    Only fires on transition to 'published' — drafts and cancellations do nothing.
    """
    if instance.status != 'published':
        return

    from bookings.models import SelectGameRSVP
    from clients.models import ClientPackage, Notification

    today = timezone.localdate()

    # Active Select members on this team (primary team) or guest-called-up to it
    team_client_ids = set()

    # Primary team members
    for cp in ClientPackage.objects.filter(
        package__package_type='select',
        status='active',
        expiry_date__gte=today,
    ).select_related('client__user', 'player'):
        if cp.player_id:
            player = cp.player
            if (player.team_id == instance.team_id or
                    instance.team_id in player.select_teams.values_list('id', flat=True)):
                team_client_ids.add(cp.client_id)

    # Guest invitees added manually
    for client in instance.guest_invitees.all():
        team_client_ids.add(client.pk)

    from clients.models import Client as ClientModel
    for client_id in team_client_ids:
        try:
            client = ClientModel.objects.get(pk=client_id)
        except ClientModel.DoesNotExist:
            continue
        _, created = SelectGameRSVP.objects.get_or_create(
            game=instance,
            client=client,
            defaults={'status': 'pending'},
        )
        if created:
            date_str = instance.date.strftime('%A, %B %-d')
            try:
                Notification.objects.create(
                    client=client,
                    notification_type='promotional',
                    title=f'APC Select Game — {date_str}',
                    message=(
                        f'{instance.team.name} has a game on {date_str} at {instance.start_time.strftime("%-I:%M %p")} '
                        f'at {instance.location}. Please RSVP on your dashboard.'
                    ),
                    method='in_app',
                )
            except Exception:
                pass  # never block fan-out on notification failure
