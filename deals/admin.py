from django.contrib import admin

from .models import ChangeLog, Deal, ProjectFile, ProjectVersion


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
    list_display = ('deal', 'source', 'category', 'original_name', 'is_archived', 'updated_at')
    list_filter = ('source', 'category', 'is_archived', 'updated_at')
    search_fields = ('deal__project_code', 'original_name', 'relative_path')
    ordering = ('-updated_at',)
