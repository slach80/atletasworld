from django.contrib import admin
from .models import ValdProfile, ValdResultDefinition, ValdTestResult, ValdSyncRun


@admin.register(ValdProfile)
class ValdProfileAdmin(admin.ModelAdmin):
    list_display = ('player', 'vald_profile_id', 'vald_tenant_id', 'match_method', 'matched_at', 'is_active')
    list_filter = ('match_method', 'is_active', 'matched_at')
    search_fields = ('player__first_name', 'player__last_name', 'vald_profile_id')
    raw_id_fields = ('player',)


@admin.register(ValdResultDefinition)
class ValdResultDefinitionAdmin(admin.ModelAdmin):
    list_display = ('result_id', 'name', 'system', 'unit', 'trend_direction', 'display_order', 'show_in_client_portal')
    list_filter = ('system', 'trend_direction', 'show_in_client_portal')
    search_fields = ('result_id', 'name')
    list_editable = ('display_order', 'show_in_client_portal')
    ordering = ('system', 'display_order', 'name')


@admin.register(ValdTestResult)
class ValdTestResultAdmin(admin.ModelAdmin):
    list_display = ('vald_test_id', 'profile', 'system', 'test_type', 'test_date', 'week_key', 'created_at')
    list_filter = ('system', 'test_type', 'test_date')
    search_fields = ('vald_test_id', 'profile__player__first_name', 'profile__player__last_name')
    date_hierarchy = 'test_date'
    raw_id_fields = ('profile',)
    readonly_fields = ('vald_test_id', 'created_at', 'updated_at', 'raw_payload')


@admin.register(ValdSyncRun)
class ValdSyncRunAdmin(admin.ModelAdmin):
    list_display = ('system', 'started_at', 'finished_at', 'status', 'records_synced', 'last_synced_at')
    list_filter = ('system', 'status', 'started_at')
    readonly_fields = ('started_at', 'finished_at', 'last_synced_at', 'error')
    ordering = ('-started_at',)
