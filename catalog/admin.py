from django.contrib import admin

from .models import CostItem, CostItemOption, Section


class CostItemOptionInline(admin.TabularInline):
    model = CostItemOption
    extra = 0
    fields = (
        'sort_order',
        'name_ru',
        'code',
        'manufacturer',
        'article',
        'country',
        'unit',
        'price',
        'is_default',
        'is_active',
        'description',
    )


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name_ru', 'kind', 'sort_order')
    list_filter = ('kind',)
    search_fields = ('code', 'name_ru')
    ordering = ('sort_order', 'code')


@admin.register(CostItem)
class CostItemAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'name_ru',
        'section',
        'category',
        'kind',
        'unit',
        'price_material',
        'price_work',
        'default_included',
        'sort_order',
        'is_active',
    )
    list_filter = ('category', 'unit', 'kind', 'section', 'is_active', 'default_included')
    search_fields = ('code', 'name_ru')
    ordering = ('category', 'sort_order', 'name_ru')
    inlines = (CostItemOptionInline,)


@admin.register(CostItemOption)
class CostItemOptionAdmin(admin.ModelAdmin):
    list_display = (
        'name_ru',
        'cost_item',
        'code',
        'manufacturer',
        'article',
        'country',
        'unit',
        'price',
        'is_default',
        'is_active',
        'sort_order',
    )
    list_filter = ('is_default', 'is_active', 'cost_item__section')
    search_fields = ('name_ru', 'code', 'cost_item__name_ru', 'cost_item__code')
    ordering = ('cost_item', 'sort_order', 'name_ru')
