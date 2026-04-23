from django.contrib import admin

from .models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'assignee', 'deal', 'due_date', 'is_done', 'completed_at', 'created_at')
    list_filter = ('is_done', 'due_date', 'assignee', 'created_at')
    search_fields = ('title', 'assignee__username', 'deal__project_code')
    ordering = ('due_date', '-created_at')
