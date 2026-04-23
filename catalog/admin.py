from django.contrib import admin

from .models import CostItem


@admin.register(CostItem)
class CostItemAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'name_ru',
        'category',
        'unit',
        'price_material',
        'price_work',
        'is_active',
    )
    list_filter = ('category', 'unit', 'is_active')
    search_fields = ('code', 'name_ru')
    ordering = ('category', 'name_ru')
