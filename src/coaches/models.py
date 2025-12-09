from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Coach(models.Model):
    """Coach profile with availability and specializations."""
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # Basic info (admin/owner created)
    slug = models.SlugField(max_length=100, unique=True, blank=True, null=True,
                            help_text="URL-friendly name (e.g., 'mirko' for /coach/mirko/)")
    bio = models.TextField(blank=True)
    photo = models.ImageField(upload_to='coaches/', blank=True, null=True)
    specializations = models.TextField(blank=True, help_text="Comma-separated list")
    certifications = models.TextField(blank=True)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    google_calendar_id = models.CharField(max_length=255, blank=True)

    # Public profile fields (coach editable after admin creates profile)
    profile_enabled = models.BooleanField(default=False,
                                          help_text="Enable public profile page (admin must set this)")
    tagline = models.CharField(max_length=200, blank=True,
                               help_text="Short tagline shown on profile")
    full_bio = models.TextField(blank=True, help_text="Extended biography for public profile")
    experience_years = models.IntegerField(default=0, help_text="Years of coaching experience")
    coaching_philosophy = models.TextField(blank=True, help_text="Your coaching philosophy")
    achievements = models.TextField(blank=True, help_text="Notable achievements and awards")

    # Social/Contact (coach editable)
    instagram_url = models.URLField(blank=True)
    facebook_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    personal_website = models.URLField(blank=True)

    # Gallery images
    gallery_image_1 = models.ImageField(upload_to='coaches/gallery/', blank=True, null=True)
    gallery_image_2 = models.ImageField(upload_to='coaches/gallery/', blank=True, null=True)
    gallery_image_3 = models.ImageField(upload_to='coaches/gallery/', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Coach {self.user.get_full_name() or self.user.username}"

    class Meta:
        ordering = ['user__first_name']


class Availability(models.Model):
    """Coach recurring weekly availability schedule."""
    DAYS_OF_WEEK = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='availabilities')
    day_of_week = models.IntegerField(choices=DAYS_OF_WEEK)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'Availabilities'
        ordering = ['day_of_week', 'start_time']


class ScheduleBlock(models.Model):
    """Coach schedule block - specific available time slots for booking."""
    SESSION_TYPE_CHOICES = [
        ('private', 'Private Training (1-on-1)'),
        ('group', 'Group Training'),
    ]

    DURATION_CHOICES = [
        (60, '60 minutes'),
        (90, '90 minutes'),
    ]

    STATUS_CHOICES = [
        ('available', 'Available'),
        ('booked', 'Fully Booked'),
        ('cancelled', 'Cancelled'),
    ]

    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='schedule_blocks')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    session_type = models.CharField(max_length=20, choices=SESSION_TYPE_CHOICES, default='private')
    duration_minutes = models.IntegerField(choices=DURATION_CHOICES, default=60)
    max_participants = models.IntegerField(default=1, help_text="1 for private, more for group")
    current_participants = models.IntegerField(default=0)
    price_override = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True,
                                         help_text="Override default pricing if set")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.coach} - {self.date} {self.start_time} ({self.get_session_type_display()})"

    @property
    def is_available(self):
        """Check if block has available spots."""
        return self.status == 'available' and self.current_participants < self.max_participants

    @property
    def spots_remaining(self):
        return self.max_participants - self.current_participants

    def check_overlap_warnings(self):
        """Check for overlapping blocks with other coaches (for awareness)."""
        overlapping = ScheduleBlock.objects.filter(
            date=self.date,
            status='available'
        ).exclude(
            coach=self.coach
        ).exclude(
            end_time__lte=self.start_time
        ).exclude(
            start_time__gte=self.end_time
        )
        return overlapping

    class Meta:
        ordering = ['date', 'start_time']
        unique_together = ['coach', 'date', 'start_time']


class SessionAttendance(models.Model):
    """Track attendance for each booking in a schedule block."""
    ATTENDANCE_STATUS = [
        ('expected', 'Expected'),
        ('present', 'Present'),
        ('late', 'Late'),
        ('absent', 'Absent/No Show'),
    ]

    schedule_block = models.ForeignKey(ScheduleBlock, on_delete=models.CASCADE, related_name='attendances')
    booking = models.OneToOneField('bookings.Booking', on_delete=models.CASCADE, related_name='attendance')
    status = models.CharField(max_length=20, choices=ATTENDANCE_STATUS, default='expected')
    check_in_time = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.booking.player} - {self.get_status_display()}"


class PlayerAssessment(models.Model):
    """Quick assessment of player performance during a session."""
    RATING_CHOICES = [
        (1, 'Needs Improvement'),
        (2, 'Developing'),
        (3, 'Competent'),
        (4, 'Proficient'),
        (5, 'Excellent'),
    ]

    TRAINING_TYPE_CHOICES = [
        ('technical', 'Technical Skills'),
        ('tactical', 'Tactical Awareness'),
        ('physical', 'Physical Conditioning'),
        ('dribbling', 'Dribbling'),
        ('passing', 'Passing'),
        ('shooting', 'Shooting'),
        ('defending', 'Defending'),
        ('goalkeeping', 'Goalkeeping'),
        ('game_play', 'Game Play/Scrimmage'),
        ('fitness', 'Fitness Training'),
        ('mixed', 'Mixed/General Training'),
    ]

    booking = models.ForeignKey('bookings.Booking', on_delete=models.CASCADE, related_name='assessments')
    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name='assessments_given')
    player = models.ForeignKey('clients.Player', on_delete=models.CASCADE, related_name='assessments')
    training_type = models.CharField(max_length=20, choices=TRAINING_TYPE_CHOICES)

    # Assessment criteria ratings (1-5)
    effort_engagement = models.IntegerField(choices=RATING_CHOICES, default=3, help_text="Effort & Engagement")
    technical_proficiency = models.IntegerField(choices=RATING_CHOICES, default=3, help_text="Technical Proficiency")
    tactical_awareness = models.IntegerField(choices=RATING_CHOICES, default=3, help_text="Tactical Awareness")
    physical_performance = models.IntegerField(choices=RATING_CHOICES, default=3, help_text="Physical Performance")
    goals_achievement = models.IntegerField(choices=RATING_CHOICES, default=3, help_text="Sessional Goals Achievement")

    focus_areas = models.TextField(blank=True, help_text="Areas to focus on for improvement")
    highlights = models.TextField(blank=True, help_text="What the player did well")
    coach_notes = models.TextField(blank=True, help_text="Private notes for coach only")
    parent_visible_notes = models.TextField(blank=True, help_text="Notes visible to parents")
    assessment_date = models.DateTimeField(auto_now_add=True)
    notification_sent = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.player} - {self.get_training_type_display()} ({self.assessment_date.date()})"

    @property
    def overall_rating(self):
        """Calculate average of all criteria."""
        total = (self.effort_engagement + self.technical_proficiency +
                 self.tactical_awareness + self.physical_performance + self.goals_achievement)
        return round(total / 5, 1)

    class Meta:
        ordering = ['-assessment_date']
