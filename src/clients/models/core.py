from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django_prometheus.models import ExportModelOperationsMixin


class Client(ExportModelOperationsMixin("client"), models.Model):
    """Client profile for parents/guardians or adult athletes."""
    CLIENT_TYPE_CHOICES = [
        ('parent', 'Parent/Guardian'),
        ('athlete', 'Athlete (18+)'),
        ('coach', 'Team Coach'),
        ('renter', 'Facility Renter'),
    ]

    APPROVAL_STATUS_CHOICES = [
        ('not_required', 'Not Required'),
        ('pending',      'Pending Approval'),
        ('approved',     'Approved'),
        ('rejected',     'Rejected'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    client_type = models.CharField(max_length=10, choices=CLIENT_TYPE_CHOICES, default='parent')
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    emergency_contact = models.CharField(max_length=100, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)

    # Approval workflow (required for coach and renter types)
    approval_status = models.CharField(
        max_length=20, choices=APPROVAL_STATUS_CHOICES, default='not_required',
        help_text='Coaches and renters require owner approval before services are enabled')
    approved_by  = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='approved_clients')
    approved_at  = models.DateTimeField(null=True, blank=True)
    rejected_at  = models.DateTimeField(null=True, blank=True)
    approval_notes = models.TextField(blank=True, help_text='Owner notes on approval/rejection')

    # Service term (start/end date+time for coach/renter access)
    term_start = models.DateTimeField(null=True, blank=True, help_text='When this client\'s access begins')
    term_end   = models.DateTimeField(null=True, blank=True, help_text='When this client\'s access expires')

    # Allowed rental services (owner configures per client)
    allowed_services = models.ManyToManyField(
        'clients.RentalService', blank=True, related_name='allowed_clients',
        help_text='Rental services this client is permitted to book')

    stripe_customer_id = models.CharField(max_length=100, blank=True,
                                           help_text="Stripe Customer ID (cus_xxx)")
    select_invited = models.BooleanField(default=False,
                                         help_text="Owner has invited this client to purchase APC Select membership")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def needs_approval(self):
        return self.client_type in ('coach', 'renter')

    @property
    def is_approved(self):
        from django.utils import timezone
        if self.approval_status != 'approved':
            return False
        now = timezone.now()
        if self.term_start and now < self.term_start:
            return False
        if self.term_end and now > self.term_end:
            return False
        return True

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username}"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user']),
        ]


class Player(ExportModelOperationsMixin("player"), models.Model):
    """Player profile for children/athletes."""
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other/Prefer not to say'),
    ]

    SKILL_LEVEL_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('elite', 'Elite/Competitive'),
    ]

    POSITION_CHOICES = [
        ('goalkeeper', 'Goalkeeper'),
        ('defender', 'Defender'),
        ('midfielder', 'Midfielder'),
        ('forward', 'Forward'),
        ('multiple', 'Multiple Positions'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='players')
    team = models.ForeignKey('clients.Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='players')
    select_teams = models.ManyToManyField(
        'clients.Team', blank=True, related_name='select_guest_players',
        limit_choices_to={'is_select': True},
        help_text="Additional Select teams this player is eligible for (guest callups)"
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    GRADE_CHOICES = [
        ('K', 'Kindergarten'),
        ('1', '1st Grade'), ('2', '2nd Grade'), ('3', '3rd Grade'),
        ('4', '4th Grade'), ('5', '5th Grade'), ('6', '6th Grade'),
        ('7', '7th Grade'), ('8', '8th Grade'), ('9', '9th Grade (Freshman)'),
        ('10', '10th Grade (Sophomore)'), ('11', '11th Grade (Junior)'),
        ('12', '12th Grade (Senior)'), ('college', 'College'),
        ('adult', 'Adult / Post-grad'),
    ]

    birth_year = models.IntegerField()
    school_grade = models.CharField(max_length=10, choices=GRADE_CHOICES, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    soccer_club = models.CharField(max_length=100, blank=True, help_text="Current soccer club")
    team_name = models.CharField(max_length=100, blank=True, help_text="Team name (e.g., U14 Boys)")
    skill_level = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, default='beginner')
    primary_position = models.CharField(max_length=20, choices=POSITION_CHOICES, blank=True)
    notes = models.TextField(blank=True, help_text="Any special needs or notes")
    photo = models.ImageField(upload_to='players/', blank=True, null=True)

    # Jersey / kit preferences
    JERSEY_SIZE_CHOICES = [
        ('', '-- Select Size --'),
        ('youth_s',  'Youth S'),
        ('youth_m',  'Youth M'),
        ('youth_l',  'Youth L'),
        ('youth_xl', 'Youth XL'),
        ('adult_s',  'Adult S'),
        ('adult_m',  'Adult M'),
        ('adult_l',  'Adult L'),
        ('adult_xl', 'Adult XL'),
    ]
    jersey_size = models.CharField(
        max_length=10, blank=True, choices=JERSEY_SIZE_CHOICES,
        help_text="Shirt/jersey size for kits and team gear"
    )
    favorite_national_team = models.CharField(
        max_length=100, blank=True,
        help_text="Player's favorite national team (free text + autocomplete from full FIFA list)"
    )
    favorite_club_team = models.CharField(
        max_length=100, blank=True,
        help_text="Player's favorite club team (e.g. PSG, LFC, Real Madrid)"
    )

    is_self = models.BooleanField(default=False,
                                  help_text='True when this Player record represents the client themselves (Athlete 18+ account type)')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.birth_year})"

    @property
    def age(self):
        return timezone.now().year - self.birth_year

    @property
    def age_group(self):
        """Returns age group like U10, U12, etc."""
        age = self.age
        if age <= 6:
            return 'U6'
        elif age <= 8:
            return 'U8'
        elif age <= 10:
            return 'U10'
        elif age <= 12:
            return 'U12'
        elif age <= 14:
            return 'U14'
        elif age <= 16:
            return 'U16'
        elif age <= 19:
            return 'U19'
        else:
            return 'Adult'

    class Meta:
        ordering = ['first_name', 'last_name']
        indexes = [
            models.Index(fields=['client', 'is_active']),
            models.Index(fields=['client', 'birth_year']),
        ]
