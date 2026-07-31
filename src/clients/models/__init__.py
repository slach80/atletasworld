"""Clients models package — re-exports all models and utilities."""
from .core import Client, Player
from .packages import (
    Package, ClientPackage, ClientCredit, SessionReservation, BookingPreference,
)
from .notifications import (
    NotificationPreference, Notification, NotificationTemplate,
    PushSubscription, NotificationSchedule, NotificationOutbox,
    UnsubscribeToken, UNSUBSCRIBE_SALT, make_unsubscribe_url, EmailSuppression,
)
from .teams_rentals import Team, RentalService, FieldRentalSlot
from .misc import (
    ClientWaiver, get_current_waiver, DiscountCode, DiscountCodeUse,
    ContactParent, ContactPlayer, EmailBroadcast, UserPasswordExpiry,
    ReferralCode, Referral, ReferralPayout,
)

__all__ = [
    # core
    'Client',
    'Player',
    # packages
    'Package',
    'ClientPackage',
    'ClientCredit',
    'SessionReservation',
    'BookingPreference',
    # notifications
    'NotificationPreference',
    'Notification',
    'NotificationTemplate',
    'PushSubscription',
    'NotificationSchedule',
    'NotificationOutbox',
    'UnsubscribeToken',
    'UNSUBSCRIBE_SALT',
    'make_unsubscribe_url',
    'EmailSuppression',
    # teams & rentals
    'Team',
    'RentalService',
    'FieldRentalSlot',
    # misc
    'ClientWaiver',
    'get_current_waiver',
    'DiscountCode',
    'DiscountCodeUse',
    'ContactParent',
    'ContactPlayer',
    'EmailBroadcast',
    'UserPasswordExpiry',
    'ReferralCode',
    'Referral',
    'ReferralPayout',
]
