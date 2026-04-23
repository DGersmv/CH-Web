from django.contrib import admin

from .models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'email', 'created_at', 'created_by')
    search_fields = ('full_name', 'phone', 'email', 'location')
    list_filter = ('created_at',)
    ordering = ('-created_at',)
