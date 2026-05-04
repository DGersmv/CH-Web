from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import DirectMessage, Notification, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Role', {'fields': ('role',)}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Role', {'fields': ('role',)}),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_staff')


@admin.register(DirectMessage)
class DirectMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'sender', 'recipient', 'body_preview', 'has_attachment', 'created_at', 'read_at')
    list_filter = ('created_at', 'read_at', 'sender', 'recipient')
    search_fields = (
        'sender__username',
        'sender__first_name',
        'sender__last_name',
        'recipient__username',
        'recipient__first_name',
        'recipient__last_name',
        'body',
    )
    ordering = ('-created_at',)
    autocomplete_fields = ('sender', 'recipient')
    readonly_fields = ('created_at',)

    @admin.display(description='Body')
    def body_preview(self, obj):
        text = (obj.body or '').strip()
        return text[:80] + ('...' if len(text) > 80 else '')

    @admin.display(boolean=True, description='Attachment')
    def has_attachment(self, obj):
        return bool(obj.attachment)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'actor',
        'notification_type',
        'title',
        'is_read',
        'created_at',
        'read_at',
        'related_model',
        'related_id',
    )
    list_filter = ('notification_type', 'is_read', 'created_at', 'read_at', 'user', 'actor')
    search_fields = (
        'title',
        'body',
        'user__username',
        'user__first_name',
        'user__last_name',
        'actor__username',
        'actor__first_name',
        'actor__last_name',
        'related_model',
    )
    ordering = ('-created_at',)
    autocomplete_fields = ('user', 'actor')
