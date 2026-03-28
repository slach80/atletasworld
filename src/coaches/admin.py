from django.contrib import admin
from django.utils.html import format_html
from .models import Coach, Availability, ScheduleBlock, SessionAttendance, PlayerAssessment


@admin.register(Coach)
class CoachAdmin(admin.ModelAdmin):
    """Admin configuration for Coach model with organized fieldsets."""

    list_display = ['get_full_name', 'user', 'slug', 'is_active', 'profile_enabled', 'hourly_rate']
    list_filter = ['is_active', 'profile_enabled']
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'slug']
    prepopulated_fields = {'slug': ('user',)}
    readonly_fields = ['created_at', 'updated_at', 'profile_preview']

    fieldsets = (
        ('Basic Information (Admin Only)', {
            'fields': ('user', 'slug', 'is_active', 'hourly_rate'),
            'description': 'Core settings managed by admin only.'
        }),
        ('Profile Access Control (Admin Only)', {
            'fields': ('profile_enabled',),
            'description': 'Enable this to allow the coach to have a public profile page and edit their profile.',
            'classes': ('wide',),
        }),
        ('Profile Preview', {
            'fields': ('profile_preview',),
            'classes': ('collapse',),
        }),
        ('Bio & Background (Admin/Coach Editable)', {
            'fields': ('photo', 'bio', 'specializations', 'certifications', 'google_calendar_id'),
            'description': 'Basic profile information.'
        }),
        ('Public Profile Content (Coach Editable)', {
            'fields': ('tagline', 'full_bio', 'experience_years', 'coaching_philosophy', 'achievements'),
            'description': 'Extended profile content visible on public coach page.',
            'classes': ('collapse',),
        }),
        ('Social Media & Contact (Coach Editable)', {
            'fields': ('instagram_url', 'facebook_url', 'twitter_url', 'linkedin_url', 'youtube_url', 'personal_website'),
            'description': 'Social media links for public profile.',
            'classes': ('collapse',),
        }),
        ('Gallery Images (Coach Editable)', {
            'fields': ('gallery_image_1', 'gallery_image_2', 'gallery_image_3'),
            'description': 'Additional images for profile gallery.',
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username
    get_full_name.short_description = 'Name'
    get_full_name.admin_order_field = 'user__first_name'

    def profile_preview(self, obj):
        if obj.slug and obj.profile_enabled:
            return format_html(
                '<a href="/coach/{}" target="_blank" class="button">View Public Profile</a>',
                obj.slug
            )
        elif obj.slug and not obj.profile_enabled:
            return format_html(
                '<span style="color: #999;">Profile not enabled. Enable above to make public.</span>'
            )
        return format_html('<span style="color: #999;">Set a slug to create profile URL.</span>')
    profile_preview.short_description = 'Public Profile'


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ['coach', 'get_day_name', 'start_time', 'end_time', 'is_active']
    list_filter = ['coach', 'day_of_week', 'is_active']
    ordering = ['coach', 'day_of_week', 'start_time']

    def get_day_name(self, obj):
        return obj.get_day_of_week_display()
    get_day_name.short_description = 'Day'


@admin.register(ScheduleBlock)
class ScheduleBlockAdmin(admin.ModelAdmin):
    list_display = ['coach', 'date', 'start_time', 'end_time', 'session_type', 'status', 'participants_display']
    list_filter = ['coach', 'date', 'session_type', 'status']
    search_fields = ['coach__user__first_name', 'coach__user__last_name']
    date_hierarchy = 'date'
    ordering = ['-date', 'start_time']

    def participants_display(self, obj):
        return f"{obj.current_participants}/{obj.max_participants}"
    participants_display.short_description = 'Participants'


@admin.register(SessionAttendance)
class SessionAttendanceAdmin(admin.ModelAdmin):
    list_display = ['get_player', 'schedule_block', 'status', 'check_in_time']
    list_filter = ['status', 'schedule_block__date']
    search_fields = ['booking__player__first_name', 'booking__player__last_name']

    def get_player(self, obj):
        return obj.booking.player
    get_player.short_description = 'Player'


@admin.register(PlayerAssessment)
class PlayerAssessmentAdmin(admin.ModelAdmin):
    list_display = ['player', 'coach', 'training_type', 'overall_rating', 'assessment_date', 'notification_sent']
    list_filter = ['coach', 'training_type', 'notification_sent', 'assessment_date']
    search_fields = ['player__first_name', 'player__last_name', 'coach__user__first_name']
    date_hierarchy = 'assessment_date'
    readonly_fields = ['overall_rating']

    fieldsets = (
        ('Session Info', {
            'fields': ('booking', 'coach', 'player', 'training_type')
        }),
        ('Ratings', {
            'fields': ('effort_engagement', 'technical_proficiency', 'tactical_awareness',
                      'physical_performance', 'goals_achievement', 'overall_rating')
        }),
        ('Notes', {
            'fields': ('focus_areas', 'highlights', 'coach_notes', 'parent_visible_notes')
        }),
        ('Status', {
            'fields': ('notification_sent',)
        }),
    )
