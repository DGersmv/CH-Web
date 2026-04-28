from decimal import Decimal

from django.db import migrations


SECTION_CODE = 'additional_options_template_v1'

OPTION_ROWS = [
    ('add_opt_01', 'Свайно-винтовой фундамент под дом', 'sqm', '5000'),
    ('add_opt_02', 'Свайно-винтовой фундамент под террасу', 'sqm', '5000'),
    ('add_opt_03', 'Терраса из доски хвойных пород на скрытом крепеже Camo', 'sqm', '14000'),
    ('add_opt_04', 'Периметральное ограждение террасы', 'lm', '6000'),
    ('add_opt_05', 'Навес над террасой со сплошной кровлей', 'sqm', '18000'),
    ('add_opt_06', 'Навес над террасой с монолитным поликарбонатом', 'sqm', '20000'),
    ('add_opt_07', 'Входное крыльцо (3кв.м.) со ступенями', 'sqm', '18000'),
    ('add_opt_08', 'Навес на вх.крыльцом с сплошной кровлей', 'sqm', '22000'),
    ('add_opt_09', 'Сетка от грызунов', 'sqm', '1000'),
    ('add_opt_10', 'Дополнительные терморегуляторы', 'pcs', '5000'),
    ('add_opt_11', 'Незамерзающий уличный кран Unipump', 'pcs', '15000'),
    ('add_opt_12', 'Дополнительный фонарь уличного освещения', 'pcs', '6000'),
]


def forwards(apps, schema_editor):
    Section = apps.get_model('catalog', 'Section')
    CostItem = apps.get_model('catalog', 'CostItem')

    section, _ = Section.objects.get_or_create(
        code=SECTION_CODE,
        defaults={
            'name_ru': 'Дополнительные опции',
            'kind': 'bathroom_template',
            'sort_order': 10,
        },
    )
    for idx, (code, name_ru, unit, price) in enumerate(OPTION_ROWS, start=1):
        CostItem.objects.update_or_create(
            code=code,
            defaults={
                'name_ru': name_ru,
                'unit': unit,
                'category': 'additional',
                'price_material': Decimal(price),
                'price_work': Decimal('0'),
                'formula_multiplier': None,
                'is_active': True,
                'section_id': section.pk,
                'kind': 'material',
                'default_included': False,
                'sort_order': idx,
            },
        )


def backwards(apps, schema_editor):
    Section = apps.get_model('catalog', 'Section')
    CostItem = apps.get_model('catalog', 'CostItem')

    CostItem.objects.filter(code__in=[row[0] for row in OPTION_ROWS]).delete()
    Section.objects.filter(code=SECTION_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0008_sync_bathroom_material_option_prices'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

