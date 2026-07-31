from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django_prometheus.models import ExportModelOperationsMixin

from .core import Client, Player


class ClientWaiver(models.Model):
    """
    Digital waiver signature for Atletas Performance Center liability release.
    Must be signed annually. Required before any session can be booked.
    """
    WAIVER_VERSION = '2026-v1'  # bump this string to invalidate all existing waivers

    client          = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='waivers')
    # Who physically signed (may differ from account holder for minors)
    full_name       = models.CharField(max_length=200, help_text='Printed name of signatory')
    signature_text  = models.CharField(max_length=200, help_text='Typed signature (full legal name)')
    guardian_name   = models.CharField(max_length=200, blank=True,
                                       help_text='Parent/guardian name if signing for a minor')
    photo_video_consent = models.BooleanField(default=False,
                                              help_text='Consent to photo/video use for promotional purposes')
    # Audit fields
    waiver_version  = models.CharField(max_length=20, default=WAIVER_VERSION)
    signed_at       = models.DateTimeField(auto_now_add=True)
    ip_address      = models.GenericIPAddressField(null=True, blank=True)
    user_agent      = models.TextField(blank=True)
    # Validity: waiver is valid for the calendar year it was signed
    valid_year      = models.IntegerField(help_text='Calendar year this waiver is valid for')

    def __str__(self):
        return f'{self.client} — waiver signed {self.signed_at:%Y-%m-%d} ({self.waiver_version})'

    @property
    def is_current(self):
        """True if this waiver covers the current calendar year and version."""
        from django.utils import timezone
        return (
            self.valid_year == timezone.now().year
            and self.waiver_version == self.WAIVER_VERSION
        )

    class Meta:
        ordering = ['-signed_at']
        indexes  = [
            models.Index(fields=['client', 'valid_year']),
            models.Index(fields=['waiver_version']),
        ]


def get_current_waiver(client):
    """Return the most recent valid waiver for a client, or None."""
    from django.utils import timezone
    return ClientWaiver.objects.filter(
        client=client,
        valid_year=timezone.now().year,
        waiver_version=ClientWaiver.WAIVER_VERSION,
    ).first()


class DiscountCode(models.Model):
    """Promotional discount codes redeemable by clients at checkout."""
    DISCOUNT_TYPE_CHOICES = [
        ('percent', 'Percentage Off'),
        ('fixed',   'Fixed Dollar Amount'),
    ]
    SCOPE_CHOICES = [
        ('all',      'All Purchases'),
        ('packages', 'Packages Only'),
        ('sessions', 'Sessions (Drop-in) Only'),
    ]

    code                = models.CharField(max_length=30, unique=True, db_index=True)
    description         = models.CharField(max_length=200, blank=True)
    discount_type       = models.CharField(max_length=10, choices=DISCOUNT_TYPE_CHOICES)
    value               = models.DecimalField(max_digits=8, decimal_places=2,
                              help_text='Percentage (0–100) or fixed dollar amount')
    scope               = models.CharField(max_length=10, choices=SCOPE_CHOICES, default='all')
    specific_packages   = models.ManyToManyField(
                              'clients.Package', blank=True, related_name='discount_codes',
                              help_text='Leave empty to apply to all packages within scope')
    specific_session_types = models.ManyToManyField(
                              'bookings.SessionType', blank=True, related_name='discount_codes',
                              help_text='Leave empty to apply to all session types within scope')
    max_uses            = models.IntegerField(null=True, blank=True,
                              help_text='Total redemption limit. Leave blank for unlimited.')
    max_uses_per_client = models.IntegerField(default=1)
    min_purchase_amount = models.DecimalField(max_digits=8, decimal_places=2,
                              null=True, blank=True,
                              help_text='Minimum purchase amount required to use this code')
    valid_from          = models.DateField(null=True, blank=True)
    valid_until         = models.DateField(null=True, blank=True)
    is_active           = models.BooleanField(default=True)
    created_by          = models.ForeignKey('auth.User', on_delete=models.SET_NULL,
                              null=True, blank=True, related_name='created_discount_codes')
    created_at          = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        val = f'{self.value}%' if self.discount_type == 'percent' else f'${self.value}'
        return f'{self.code} ({val} off)'

    @property
    def use_count(self):
        return self.uses.filter(status='applied').count()

    def is_valid_now(self):
        from django.utils import timezone
        today = timezone.localdate()
        if not self.is_active:
            return False, 'Code is inactive.'
        if self.valid_from and today < self.valid_from:
            return False, 'Code is not yet valid.'
        if self.valid_until and today > self.valid_until:
            return False, 'Code has expired.'
        if self.max_uses is not None and self.use_count >= self.max_uses:
            return False, 'Code has reached its usage limit.'
        return True, ''

    def compute_discount(self, subtotal):
        """Return Decimal discount amount for the given subtotal."""
        from decimal import Decimal
        if self.discount_type == 'percent':
            return (subtotal * self.value / Decimal('100')).quantize(Decimal('0.01'))
        return min(self.value, subtotal)

    class Meta:
        ordering = ['-created_at']


class DiscountCodeUse(models.Model):
    """Records each redemption of a DiscountCode."""
    STATUS_CHOICES = [
        ('pending',   'Pending'),    # validated, payment not yet confirmed
        ('applied',   'Applied'),    # payment confirmed
        ('cancelled', 'Cancelled'),
    ]

    code                     = models.ForeignKey(DiscountCode, on_delete=models.PROTECT,
                                   related_name='uses')
    client                   = models.ForeignKey('Client', on_delete=models.CASCADE,
                                   related_name='discount_uses')
    discount_amount          = models.DecimalField(max_digits=8, decimal_places=2)
    original_amount          = models.DecimalField(max_digits=8, decimal_places=2)
    final_amount             = models.DecimalField(max_digits=8, decimal_places=2)
    status                   = models.CharField(max_length=15, choices=STATUS_CHOICES,
                                   default='pending')
    applied_to_package       = models.ForeignKey('clients.ClientPackage', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='discount_uses')
    applied_to_booking       = models.ForeignKey('bookings.Booking', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='discount_uses')
    stripe_payment_intent_id = models.CharField(max_length=100, blank=True)
    used_at                  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.code.code} — {self.client} saved ${self.discount_amount}'

    class Meta:
        ordering = ['-used_at']


# ============================================================================
# CONTACT IMPORT (pre-registration contacts from past events/programs)
# ============================================================================

class ContactParent(models.Model):
    """
    A parent/guardian contact imported from past APC event registrations.
    Linked to a Client once they create an account with a matching email.
    """
    SOURCE_CHOICES = [
        ('sp_camp',         'S&P Camp'),
        ('apc_summer_2025', 'APC Summer Program 2025'),
        ('aw_summer_2025',  'AW Summer 2025'),
        ('ff_camp_jun_2024','Future Footballers Camp Jun 2024'),
        ('ff_camp_jul_2024','Future Footballers Camp Jul 2024'),
        ('ff_program',      'Future Footballers Program'),
        ('nkc_spring_2025', 'NKC Spring Break 2025'),
        ('winter_2024',     'Winter Clinic 2024'),
        ('manual',          'Manually Added'),
        ('other',           'Other'),
    ]

    email          = models.EmailField(blank=True, db_index=True)
    phone          = models.CharField(max_length=30, blank=True)
    first_name     = models.CharField(max_length=100, blank=True)
    last_name      = models.CharField(max_length=100, blank=True)
    notes          = models.TextField(blank=True)
    source         = models.CharField(max_length=30, choices=SOURCE_CHOICES, default='other')

    # Linked once parent creates an APC account
    client         = models.OneToOneField(
        'Client', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contact_import'
    )
    linked_at      = models.DateTimeField(null=True, blank=True)

    imported_at    = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    def __str__(self):
        name = f'{self.first_name} {self.last_name}'.strip() or self.email or self.phone
        return f'{name} ({self.player_count} players)'

    @property
    def player_count(self):
        return self.players.count()

    @property
    def is_linked(self):
        return self.client_id is not None

    @property
    def display_name(self):
        return f'{self.first_name} {self.last_name}'.strip() or self.email

    class Meta:
        ordering = ['last_name', 'first_name', 'email']
        indexes  = [
            models.Index(fields=['email']),
            models.Index(fields=['client']),
        ]


class ContactPlayer(models.Model):
    """A player/child associated with a ContactParent from imported event data."""

    SEX_CHOICES = [('M', 'Male'), ('F', 'Female'), ('', 'Unknown')]

    parent       = models.ForeignKey(ContactParent, on_delete=models.CASCADE, related_name='players')
    first_name   = models.CharField(max_length=100)
    last_name    = models.CharField(max_length=100, blank=True)
    birth_year   = models.IntegerField(null=True, blank=True)
    dob          = models.CharField(max_length=30, blank=True, help_text='Raw DOB from source')
    sex          = models.CharField(max_length=1, choices=SEX_CHOICES, blank=True)
    club_team    = models.CharField(max_length=150, blank=True)
    position     = models.CharField(max_length=100, blank=True)
    tshirt_size  = models.CharField(max_length=10, blank=True)
    notes        = models.TextField(blank=True)
    source       = models.CharField(max_length=30, blank=True)

    # Linked to a real Player record once the parent creates their APC account
    player       = models.OneToOneField(
        'Player', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contact_import'
    )
    linked_at    = models.DateTimeField(null=True, blank=True)

    imported_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.birth_year or "?"}) — {self.parent.email}'

    @property
    def is_linked(self):
        return self.player_id is not None

    @property
    def display_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    class Meta:
        ordering = ['last_name', 'first_name']
        indexes  = [
            models.Index(fields=['parent', 'birth_year']),
        ]


class EmailBroadcast(models.Model):
    """Log of bulk email sends from the owner notification center."""
    recipient_group  = models.CharField(max_length=50)
    subject          = models.CharField(max_length=255)
    sent_count       = models.IntegerField(default=0)
    failed_count     = models.IntegerField(default=0)
    recipient_emails = models.TextField(blank=True)  # comma-separated, for audit
    sent_by          = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.subject} → {self.recipient_group} ({self.sent_count} sent)'


class UserPasswordExpiry(models.Model):
    """Tracks when a user last changed their password for annual expiry enforcement."""
    user               = models.OneToOneField(User, on_delete=models.CASCADE, related_name='password_expiry')
    password_changed_at = models.DateTimeField(default=timezone.now)

    PASSWORD_EXPIRY_DAYS = 365

    class Meta:
        verbose_name        = 'Password Expiry'
        verbose_name_plural = 'Password Expiries'

    def __str__(self):
        return f'{self.user.username} — changed {self.password_changed_at.date()}'

    @property
    def is_expired(self):
        return (timezone.now() - self.password_changed_at).days >= self.PASSWORD_EXPIRY_DAYS

    @property
    def days_until_expiry(self):
        return max(0, self.PASSWORD_EXPIRY_DAYS - (timezone.now() - self.password_changed_at).days)


class ReferralCode(models.Model):
    """Unique referral code for each user. Generated on account creation or on-demand."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='referral_code')
    code = models.CharField(max_length=20, unique=True, db_index=True,
                           help_text="8-character uppercase alphanumeric code")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['code'])]

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.code}'


class Referral(models.Model):
    """Tracks a single referral relationship between referrer and referred user."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),       # Referred signed up, hasn't purchased yet
        ('activated', 'Activated'),   # First purchase made, reward granted
        ('expired', 'Expired'),       # Window expired without purchase
    ]
    REFERRER_TYPE_CHOICES = [
        ('client', 'Client'),
        ('coach', 'Coach'),
    ]

    referrer_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='referrals_given')
    referred_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='referrals_received')
    referral_code = models.CharField(max_length=20, db_index=True,
                                     help_text="Code used for this referral (audit trail)")
    referrer_type = models.CharField(max_length=10, choices=REFERRER_TYPE_CHOICES,
                                    help_text="Determines reward percentage: client=10%, coach=20%")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Activation details
    activated_at = models.DateTimeField(null=True, blank=True)
    activation_purchase_amount = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True,
                                                     help_text="Amount of first purchase that triggered activation")
    reward_amount = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True,
                                       help_text="Calculated reward (10% or 20% of purchase)")

    # Expiry tracking
    referral_window_expires = models.DateTimeField(
        help_text="Referred user must make first purchase by this date (signup + 60 days)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['referrer_user', 'status']),
            models.Index(fields=['referred_user', 'status']),
            models.Index(fields=['status', 'referral_window_expires']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['referred_user'], name='one_referral_per_user')
        ]

    def __str__(self):
        return f'{self.referrer_user.get_full_name()} → {self.referred_user.get_full_name()} ({self.status})'

    @property
    def is_within_window(self):
        """Check if referral window is still open."""
        return timezone.now() < self.referral_window_expires


class ReferralPayout(models.Model):
    """Payout request for coach referrals. Owner-reviewed before payment."""
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
    ]

    referral = models.OneToOneField(Referral, on_delete=models.CASCADE, related_name='payout')
    coach_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='referral_payouts')
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')

    # Review details
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='reviewed_payouts')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # Payment details
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_notes = models.TextField(blank=True,
                                    help_text="Check number, Venmo reference, bank transfer details, etc.")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['coach_user', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f'{self.coach_user.get_full_name()} — ${self.amount} ({self.get_status_display()})'

    def approve(self, reviewed_by):
        """Approve payout for payment."""
        self.status = 'approved'
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.save()

    def reject(self, reviewed_by, reason=''):
        """Reject payout."""
        self.status = 'rejected'
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.rejection_reason = reason
        self.save()

    def mark_paid(self, payment_notes=''):
        """Mark payout as paid."""
        self.status = 'paid'
        self.paid_at = timezone.now()
        if payment_notes:
            self.payment_notes = payment_notes
        self.save()
