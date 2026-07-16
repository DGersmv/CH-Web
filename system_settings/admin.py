from django.contrib import admin

from .models import IntegrationToken, PlatformJob, SystemConfig


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'updated_by', 'updated_at')
    search_fields = ('key', 'value')


@admin.register(IntegrationToken)
class IntegrationTokenAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'is_active', 'last_used_at', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'owner__username')
    readonly_fields = ('key', 'created_at', 'last_used_at')


@admin.register(PlatformJob)
class PlatformJobAdmin(admin.ModelAdmin):
    list_display = ('job_type', 'status', 'run_after', 'attempts', 'created_at')
    list_filter = ('status', 'job_type')
    search_fields = ('job_type',)
    readonly_fields = ('created_at', 'started_at', 'finished_at')
