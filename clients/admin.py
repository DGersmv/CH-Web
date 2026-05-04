from django.contrib import admin

from .models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('full_name_display', 'phone', 'email', 'created_at', 'created_by')
    search_fields = ('last_name', 'first_name', 'middle_name', 'company_name', 'phone', 'email', 'notes')
    list_filter = ('created_at',)
    ordering = ('company_name', 'last_name', 'first_name', 'middle_name')

    @admin.display(description='Клиент')
    def full_name_display(self, obj):
        return obj.full_name
