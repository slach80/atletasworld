"""
Performance tracking models for VALD API integration.

Stores athlete profiles, test results, metric definitions, and sync audit records.
"""
from django.db import models
from django.utils import timezone


class ValdProfile(models.Model):
    """Links a Player to a VALD athlete profile."""

    MATCH_METHOD_CHOICES = [
        ('manual', 'Manual'),
        ('auto_name_dob', 'Auto (Name + DOB)'),
        ('vald_invite', 'VALD Invite'),
    ]

    player = models.OneToOneField(
        'clients.Player',
        on_delete=models.CASCADE,
        related_name='vald_profile'
    )
    vald_profile_id = models.CharField(max_length=64, unique=True, db_index=True)
    vald_tenant_id = models.CharField(max_length=64, db_index=True)
    matched_at = models.DateTimeField(auto_now=True)
    match_method = models.CharField(
        max_length=20,
        choices=MATCH_METHOD_CHOICES,
        default='manual',
        help_text="How this Player was linked to the VALD profile"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'VALD Profile'
        verbose_name_plural = 'VALD Profiles'
        indexes = [
            models.Index(fields=['vald_tenant_id', 'is_active']),
        ]

    def __str__(self):
        return f"{self.player.first_name} {self.player.last_name} → VALD {self.vald_profile_id}"


class ValdResultDefinition(models.Model):
    """
    Metric metadata pulled from VALD /resultdefinitions.

    Drives UI labels, units, and trend polarity (higher/lower = better).
    """

    TREND_DIRECTION_CHOICES = [
        ('increasing', 'Increasing (higher is better)'),
        ('decreasing', 'Decreasing (lower is better)'),
        ('', 'Neutral'),
    ]

    result_id = models.CharField(max_length=64, primary_key=True)
    system = models.CharField(max_length=20, db_index=True)
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=40, blank=True)
    trend_direction = models.CharField(
        max_length=10,
        choices=TREND_DIRECTION_CHOICES,
        blank=True,
        help_text="Polarity for progress charts"
    )
    display_order = models.IntegerField(
        default=0,
        help_text="Owner-curated order for client portal charts"
    )
    show_in_client_portal = models.BooleanField(
        default=False,
        help_text="Gate this metric's visibility to parents"
    )
    description = models.TextField(
        blank=True,
        help_text="Parent-friendly explanation of what this metric measures"
    )
    raw_payload = models.JSONField(default=dict)
    refreshed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'VALD Result Definition'
        verbose_name_plural = 'VALD Result Definitions'
        ordering = ['system', 'display_order', 'name']
        indexes = [
            models.Index(fields=['system', 'show_in_client_portal']),
        ]

    def __str__(self):
        return f"{self.name} ({self.system})"


class ValdTestResult(models.Model):
    """
    System-agnostic VALD test result.

    One row per test; supports ForceDecks, SmartSpeed, and all other VALD systems.
    """

    SYSTEM_CHOICES = [
        ('forcedecks', 'ForceDecks'),
        ('smartspeed', 'SmartSpeed'),
        ('dynamo', 'DynaMo'),
        ('forceframe', 'ForceFrame'),
        ('humantrak', 'HumanTrak'),
        ('nordbord', 'NordBord'),
    ]

    vald_test_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Idempotency key from VALD"
    )
    profile = models.ForeignKey(
        ValdProfile,
        on_delete=models.CASCADE,
        related_name='results'
    )
    system = models.CharField(max_length=20, choices=SYSTEM_CHOICES, db_index=True)
    test_type = models.CharField(
        max_length=80,
        help_text="e.g. 'CMJ', 'Sprint_10m'"
    )
    test_date = models.DateTimeField(db_index=True)
    raw_payload = models.JSONField(
        help_text="Full VALD response for re-derivation"
    )
    metrics = models.JSONField(
        default=dict,
        help_text="Flattened {resultId: value} for queryable columns"
    )
    week_key = models.CharField(
        max_length=10,
        db_index=True,
        help_text="ISO week: '2026-W29'"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'VALD Test Result'
        verbose_name_plural = 'VALD Test Results'
        ordering = ['-test_date']
        indexes = [
            models.Index(fields=['profile', '-test_date']),
            models.Index(fields=['system', 'test_type', '-test_date']),
            models.Index(fields=['week_key']),
        ]

    def __str__(self):
        return f"{self.profile.player.first_name} {self.profile.player.last_name} · {self.test_type} · {self.test_date.date()}"

    @property
    def iso_week(self):
        """Derive ISO week key from test_date."""
        return self.test_date.strftime('%G-W%V')


class ValdSyncRun(models.Model):
    """
    Audit log and cursor for incremental VALD syncs.

    Each sync (profiles / forcedecks / smartspeed) creates one run record.
    """

    STATUS_CHOICES = [
        ('running', 'Running'),
        ('ok', 'OK'),
        ('error', 'Error'),
    ]

    system = models.CharField(
        max_length=20,
        db_index=True,
        help_text="'profiles' | 'forcedecks' | 'smartspeed' | ..."
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='running'
    )
    records_synced = models.IntegerField(default=0)
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Cursor for incremental pulls (modifiedFromUtc)"
    )
    error = models.TextField(blank=True)

    class Meta:
        verbose_name = 'VALD Sync Run'
        verbose_name_plural = 'VALD Sync Runs'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['system', '-started_at']),
            models.Index(fields=['status', '-started_at']),
        ]

    def __str__(self):
        return f"{self.system} sync at {self.started_at} ({self.status})"

    @classmethod
    def cursor(cls, system):
        """
        Get the incremental-pull cursor for a system.

        Returns the last_synced_at timestamp from the latest successful run,
        or a far-past date for the first sync.
        """
        last_ok = cls.objects.filter(
            system=system,
            status='ok',
            last_synced_at__isnull=False
        ).first()

        if last_ok:
            return last_ok.last_synced_at.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        # First sync: start from 2000-01-01
        return '2000-01-01T00:00:00.000Z'

    def finish_ok(self, records_synced=0, last_synced_at=None):
        """Mark this run as successful."""
        self.status = 'ok'
        self.records_synced = records_synced
        self.finished_at = timezone.now()
        if last_synced_at:
            self.last_synced_at = last_synced_at
        self.save()

    def finish_error(self, error_msg):
        """Mark this run as failed."""
        self.status = 'error'
        self.error = error_msg
        self.finished_at = timezone.now()
        self.save()
