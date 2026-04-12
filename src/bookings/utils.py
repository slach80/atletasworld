"""
Shared utilities for the bookings app.

Contains pricing helpers and permission checks used by the booking API
to apply APC Select member discounts and identify team coaches.
"""
from decimal import Decimal
from django.utils import timezone


# APC Select membership gives a flat $5 rate on pickup games and
# a 10% discount on clinics and camps.
SELECT_PICKUP_PRICE = Decimal('5.00')
SELECT_DISCOUNT_FORMATS = {'camp', 'clinic'}   # 10% off for Select members
SELECT_PICKUP_FORMATS = {'pickup'}             # flat $5 for Select members


def apply_select_discount(price, session_format):
    """Return the APC Select member price for a session, or None if no discount applies.

    Select members get:
    - A flat $5 rate on pickup games (regardless of normal price).
    - 10% off clinics and camps.
    - No discount on all other session formats (private, group, etc.).

    Args:
        price (Decimal): The standard session price.
        session_format (str): The session_format value from SessionType.

    Returns:
        Decimal | None: Discounted price, or None if this format has no Select discount.
    """
    if session_format in SELECT_PICKUP_FORMATS:
        return SELECT_PICKUP_PRICE
    if session_format in SELECT_DISCOUNT_FORMATS:
        return (price * Decimal('0.90')).quantize(Decimal('0.01'))
    return None


def get_client_select_membership(user):
    """Return True if the user currently holds an active APC Select package.

    Used to gate pricing discounts in the booking API without exposing
    the package query everywhere.

    Args:
        user: A Django User instance (may be anonymous).

    Returns:
        bool: True if the user has an active, non-expired Select ClientPackage.
    """
    if not user.is_authenticated or not hasattr(user, 'client'):
        return False
    today = timezone.localdate()
    return user.client.packages.filter(
        package__package_type='select',
        status='active',
        expiry_date__gte=today,
    ).exists()


def is_team_coach(user):
    """Return True if the user should see team session types in the booking calendar.

    Regular parent/athlete accounts see only individual session types.
    Coaches (Coach model) and clients with client_type='coach' see team sessions too.

    Args:
        user: A Django User instance.

    Returns:
        bool: True if the user is a coach or team manager.
    """
    if hasattr(user, 'coach'):
        return True
    if hasattr(user, 'client') and user.client.client_type == 'coach':
        return True
    return False


def notify_pending_payment(booking, amount_due):
    """Send in-app notifications to the coach and all owners when a drop-in booking
    is awaiting payment.

    Drop-in bookings hold a slot for 24 hours. This notification lets staff know
    so they can follow up if payment doesn't arrive.

    Args:
        booking: A Booking model instance (already saved).
        amount_due (Decimal): The amount the client still needs to pay.

    Note:
        Errors are silently swallowed — a notification failure must never
        block a booking from being created.
    """
    try:
        from clients.models import Notification
        from django.contrib.auth.models import User
        player_name = str(booking.player) if booking.player else booking.client.user.get_full_name()
        session_name = booking.session_type.name if booking.session_type else 'Session'
        date_str = booking.scheduled_date.strftime('%b %-d') if booking.scheduled_date else ''
        msg = (f"{player_name} reserved {session_name} on {date_str} "
               f"— awaiting payment of ${amount_due:.2f}. Session held for 24 hours.")
        # Notify the assigned coach (if they have a client profile for in-app messages)
        if booking.coach and hasattr(booking.coach, 'user'):
            if hasattr(booking.coach.user, 'client'):
                Notification.objects.create(
                    client=booking.coach.user.client,
                    notification_type='promotional',
                    title=f'Pending Payment: {player_name}',
                    message=msg, method='in_app',
                )
        # Notify all Owner-group users
        for owner in User.objects.filter(groups__name='Owner'):
            if hasattr(owner, 'client'):
                Notification.objects.create(
                    client=owner.client,
                    notification_type='promotional',
                    title=f'Pending Payment: {session_name} — ${amount_due:.2f}',
                    message=msg, method='in_app',
                )
    except Exception:
        pass  # never block a booking due to a notification failure


# Keep legacy underscore-prefixed alias
_notify_pending_payment = notify_pending_payment
