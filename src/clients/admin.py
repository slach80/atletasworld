from django.contrib import admin
from .models import (
    Client, Player, Package, ClientPackage, NotificationPreference,
    Notification, NotificationTemplate, BookingPreference, SessionReservation,
    PushSubscription, NotificationSchedule
)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['user', 'client_type', 'phone', 'created_at']
    list_filter = ['client_type', 'created_at']
    search_fields = ['user__email', 'user__first_name', 'user__last_name', 'phone']
    raw_id_fields = ['user']


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'last_name', 'client', 'birth_year', 'skill_level', 'is_active']
    list_filter = ['skill_level', 'gender', 'is_active']
    search_fields = ['first_name', 'last_name', 'client__user__email']
    raw_id_fields = ['client']


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ['name', 'package_type', 'price', 'sessions_included', 'validity_weeks', 'is_active']
    list_filter = ['package_type', 'is_active', 'is_special']
    search_fields = ['name']


@admin.register(ClientPackage)
class ClientPackageAdmin(admin.ModelAdmin):
    list_display = ['client', 'package', 'sessions_remaining', 'sessions_used', 'status', 'expiry_date']
    list_filter = ['status', 'package']
    search_fields = ['client__user__email', 'client__user__first_name']
    raw_id_fields = ['client', 'package', 'player']
    date_hierarchy = 'expiry_date'


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ['client', 'booking_confirmations', 'booking_reminders', 'promotional_updates']
    list_filter = ['booking_confirmations', 'promotional_updates']
    raw_id_fields = ['client']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['client', 'notification_type', 'title', 'method', 'status', 'sent_at', 'created_at']
    list_filter = ['notification_type', 'method', 'status', 'created_at']
    search_fields = ['client__user__email', 'title', 'message']
    raw_id_fields = ['client', 'booking', 'package']
    readonly_fields = ['sent_at', 'read_at', 'created_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        (None, {
            'fields': ('client', 'notification_type', 'title', 'message', 'method')
        }),
        ('Status', {
            'fields': ('status', 'sent_at', 'read_at', 'created_at')
        }),
        ('Related Objects', {
            'fields': ('booking', 'package'),
            'classes': ('collapse',)
        }),
    )


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'template_type', 'is_active', 'created_at', 'updated_at']
    list_filter = ['template_type', 'is_active']
    search_fields = ['name', 'description', 'email_subject']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        (None, {
            'fields': ('name', 'template_type', 'description', 'is_active')
        }),
        ('Email Content', {
            'fields': ('email_subject', 'email_body_html', 'email_body_text'),
            'description': 'Use Django template syntax: {{ client_name }}, {{ date }}, {{ time }}, etc.'
        }),
        ('SMS Content', {
            'fields': ('sms_body',),
            'description': 'Limited to 160 characters'
        }),
        ('Targeting', {
            'fields': ('target_filters',),
            'classes': ('collapse',),
            'description': 'JSON filter criteria for automated campaigns'
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['send_test_email', 'duplicate_template', 'send_campaign_now', 'preview_recipients']

    def send_test_email(self, request, queryset):
        """Send a test email to the admin."""
        from .services import NotificationService
        for template in queryset:
            context = {
                'client_name': 'Test User',
                'date': 'December 15, 2024',
                'time': '3:00 PM',
                'session_type': 'Private Training',
                'coach_name': 'Coach Mirko',
                'site_url': 'http://localhost:8000',
            }
            success, message = NotificationService.send_email(
                to_email=request.user.email,
                subject=f"[TEST] {template.render_email_subject(context)}",
                html_content=template.render_email_body_html(context),
                text_content=template.render_email_body_text(context),
                context=context
            )
            if success:
                self.message_user(request, f"Test email sent for '{template.name}'")
            else:
                self.message_user(request, f"Failed to send test email: {message}", level='error')
    send_test_email.short_description = "Send test email to yourself"

    def duplicate_template(self, request, queryset):
        """Duplicate selected templates."""
        for template in queryset:
            template.pk = None
            template.name = f"{template.name} (Copy)"
            template.is_active = False
            template.save()
        self.message_user(request, f"Duplicated {queryset.count()} template(s)")
    duplicate_template.short_description = "Duplicate selected templates"

    def send_campaign_now(self, request, queryset):
        """Send campaign immediately to targeted clients."""
        from .tasks import send_custom_campaign, run_task
        for template in queryset:
            if not template.is_active:
                self.message_user(
                    request,
                    f"Template '{template.name}' is inactive. Activate it first.",
                    level='warning'
                )
                continue
            run_task(send_custom_campaign, template.id, template.target_filters)
            self.message_user(request, f"Campaign '{template.name}' sending...")
    send_campaign_now.short_description = "🚀 Send campaign now"

    def preview_recipients(self, request, queryset):
        """Preview how many clients will receive the campaign."""
        from django.utils import timezone
        from datetime import timedelta
        for template in queryset:
            filters = template.target_filters or {}
            clients = Client.objects.filter(user__is_active=True)

            if filters.get('has_active_package'):
                clients = clients.filter(
                    packages__status='active',
                    packages__expiry_date__gte=timezone.now().date()
                )
            if filters.get('inactive_weeks'):
                weeks = filters['inactive_weeks']
                cutoff = timezone.now() - timedelta(weeks=weeks)
                clients = clients.exclude(bookings__scheduled_date__gte=cutoff.date())
            if filters.get('min_sessions'):
                clients = clients.filter(packages__sessions_used__gte=filters['min_sessions'])

            count = clients.distinct().count()
            self.message_user(
                request,
                f"Template '{template.name}' would be sent to {count} client(s)"
            )
    preview_recipients.short_description = "👥 Preview recipient count"


@admin.register(BookingPreference)
class BookingPreferenceAdmin(admin.ModelAdmin):
    list_display = ['client', 'auto_filter', 'created_at']
    raw_id_fields = ['client']
    filter_horizontal = ['favorite_coaches']


@admin.register(SessionReservation)
class SessionReservationAdmin(admin.ModelAdmin):
    list_display = ['client', 'player', 'schedule_block', 'is_confirmed', 'expires_at', 'created_at']
    list_filter = ['is_confirmed', 'created_at']
    raw_id_fields = ['client', 'player', 'schedule_block']


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['client', 'is_active', 'user_agent', 'created_at', 'last_used_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['client__user__email', 'client__user__first_name']
    raw_id_fields = ['client']
    readonly_fields = ['endpoint', 'p256dh_key', 'auth_key', 'created_at', 'last_used_at']

    actions = ['deactivate_subscriptions']

    def deactivate_subscriptions(self, request, queryset):
        """Deactivate selected push subscriptions."""
        count = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {count} subscription(s)")
    deactivate_subscriptions.short_description = "Deactivate selected subscriptions"


@admin.register(NotificationSchedule)
class NotificationScheduleAdmin(admin.ModelAdmin):
    list_display = ['name', 'template', 'scheduled_datetime', 'status', 'recipients_count', 'sent_count', 'failed_count']
    list_filter = ['status', 'scheduled_datetime', 'template']
    search_fields = ['name', 'template__name']
    raw_id_fields = ['template', 'created_by']
    readonly_fields = ['recipients_count', 'sent_count', 'failed_count', 'executed_at', 'created_at']
    date_hierarchy = 'scheduled_datetime'

    fieldsets = (
        (None, {
            'fields': ('name', 'template', 'scheduled_datetime', 'status')
        }),
        ('Targeting', {
            'fields': ('target_filters',),
            'classes': ('collapse',),
        }),
        ('Statistics', {
            'fields': ('recipients_count', 'sent_count', 'failed_count', 'executed_at'),
            'classes': ('collapse',),
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['cancel_schedules', 'execute_now']

    def cancel_schedules(self, request, queryset):
        """Cancel scheduled notifications."""
        count = queryset.filter(status='scheduled').update(status='cancelled')
        self.message_user(request, f"Cancelled {count} schedule(s)")
    cancel_schedules.short_description = "Cancel selected schedules"

    def execute_now(self, request, queryset):
        """Execute scheduled notifications immediately."""
        from .tasks import send_custom_campaign, run_task
        for schedule in queryset.filter(status__in=['draft', 'scheduled']):
            schedule.status = 'running'
            schedule.save()
            run_task(send_custom_campaign, schedule.template.id, schedule.target_filters)
            self.message_user(request, f"Executing schedule: {schedule.name}")
    execute_now.short_description = "🚀 Execute now"
