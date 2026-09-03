from django.contrib import admin

from .models import (
    ChangeLog,
    Deal,
    DealApproval,
    DealDesignSection,
    LibraryAsset,
    ProjectFile,
    ProjectVersion,
    ServiceRequest,
    ServiceRequestEvent,
    TelegramBotState,
    TelegramGroupThread,
    TelegramProfile,
    UmnikChatAttachment,
    UmnikChatThread,
)


class ProjectVersionInline(admin.TabularInline):
    model = ProjectVersion
    extra = 0
    fields = ('version_number', 'source', 'status', 'created_by', 'created_at')
    readonly_fields = ('created_at',)
    ordering = ('-version_number',)


@admin.register(ProjectVersion)
class ProjectVersionAdmin(admin.ModelAdmin):
    list_display = ('deal', 'version_number', 'source', 'status', 'created_by', 'created_at')
    list_filter = ('source', 'status', 'created_at')
    search_fields = ('deal__project_code',)
    ordering = ('-created_at',)


@admin.register(ChangeLog)
class ChangeLogAdmin(admin.ModelAdmin):
    list_display = ('project_version', 'field_path', 'changed_by', 'changed_at')
    list_filter = ('changed_at', 'changed_by')
    search_fields = ('project_version__deal__project_code', 'field_path')
    ordering = ('-changed_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = (
        'project_code',
        'project_code_normalized',
        'module_count',
        'status',
        'client',
        'assigned_manager',
        'margin_percent',
        'updated_at',
    )
    list_filter = ('status', 'module_count', 'assigned_manager', 'created_at', 'updated_at')
    search_fields = (
        'project_code',
        'project_code_normalized',
        'code_client_name',
        'code_site_name',
        'client__last_name',
        'client__first_name',
        'client__company_name',
    )
    ordering = ('-updated_at',)
    inlines = (ProjectVersionInline,)


@admin.register(ProjectFile)
class ProjectFileAdmin(admin.ModelAdmin):
    list_display = ('deal', 'source', 'category', 'original_name', 'approval', 'is_archived', 'updated_at')
    list_filter = ('source', 'category', 'is_archived', 'updated_at')
    search_fields = ('deal__project_code', 'original_name', 'relative_path')
    raw_id_fields = ('deal', 'project_version', 'approval')
    ordering = ('-updated_at',)


@admin.register(LibraryAsset)
class LibraryAssetAdmin(admin.ModelAdmin):
    list_display = ('section', 'module_group', 'supplier_category', 'original_name', 'uploaded_by', 'created_at', 'updated_at')
    list_filter = ('section', 'module_group', 'supplier_category', 'created_at', 'updated_at')
    search_fields = ('original_name', 'relative_path', 'mime_type', 'ext')
    ordering = ('-updated_at',)


@admin.register(DealApproval)
class DealApprovalAdmin(admin.ModelAdmin):
    list_display = ('deal', 'title', 'slug', 'status', 'is_required', 'is_custom', 'decided_by', 'decided_at', 'updated_at')
    list_filter = ('status', 'is_required', 'is_custom', 'slug', 'updated_at')
    search_fields = ('deal__project_code', 'title', 'slug', 'comment')
    ordering = ('deal', 'sort_order')
    autocomplete_fields = ('deal',)


@admin.register(DealDesignSection)
class DealDesignSectionAdmin(admin.ModelAdmin):
    list_display = ('deal', 'title', 'slug', 'status', 'is_required', 'is_custom', 'decided_by', 'decided_at', 'updated_at')
    list_filter = ('status', 'is_required', 'is_custom', 'slug', 'updated_at')
    search_fields = ('deal__project_code', 'title', 'slug', 'comment')
    ordering = ('deal', 'sort_order')
    autocomplete_fields = ('deal',)


class UmnikChatAttachmentInline(admin.TabularInline):
    model = UmnikChatAttachment
    extra = 0
    fields = ('original_name', 'origin', 'mime_type', 'size_bytes', 'message', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(UmnikChatThread)
class UmnikChatThreadAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'kind', 'deal', 'updated_at')
    list_filter = ('kind', 'updated_at')
    search_fields = ('title', 'user__username', 'deal__project_code')
    ordering = ('-updated_at',)
    inlines = [UmnikChatAttachmentInline]


@admin.register(UmnikChatAttachment)
class UmnikChatAttachmentAdmin(admin.ModelAdmin):
    list_display = ('original_name', 'thread', 'origin', 'mime_type', 'size_bytes', 'created_at')
    list_filter = ('origin', 'created_at')
    search_fields = ('original_name', 'source_path', 'thread__title')
    ordering = ('-created_at',)


class ServiceRequestEventInline(admin.TabularInline):
    model = ServiceRequestEvent
    extra = 0
    fields = ('kind', 'text', 'author', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ('number', 'kind', 'status', 'priority', 'title', 'deal', 'client', 'assignee', 'created_at')
    list_filter = ('kind', 'status', 'priority', 'source', 'created_at')
    search_fields = ('number', 'title', 'description', 'reporter_name', 'reporter_phone', 'deal__project_code')
    raw_id_fields = ('deal', 'client')
    ordering = ('-created_at',)
    inlines = (ServiceRequestEventInline,)


@admin.register(TelegramProfile)
class TelegramProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'telegram_user_id', 'telegram_username', 'linked_at')
    search_fields = ('user__username', 'telegram_username', 'telegram_user_id')
    readonly_fields = ('linked_at',)


@admin.register(TelegramGroupThread)
class TelegramGroupThreadAdmin(admin.ModelAdmin):
    list_display = ('chat_id', 'title', 'thread', 'updated_at')
    search_fields = ('chat_id', 'title')


@admin.register(TelegramBotState)
class TelegramBotStateAdmin(admin.ModelAdmin):
    list_display = ('id', 'update_offset', 'updated_at')
