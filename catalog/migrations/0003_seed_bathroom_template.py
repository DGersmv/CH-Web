# Data migration: Section bathroom_template_v1 + CostItem rows from _bathroom_sheet_totals()

from decimal import Decimal

from django.db import migrations


SECTION_CODE = 'bathroom_template_v1'

MATERIAL_SPECS = [
    ('1', '11000'),
    ('1', '60000'),
    ('0', '50000'),
    ('1', '29000'),
    ('0', '15000'),
    ('0', '70000'),
    ('1', '12000'),
    ('1', '10000'),
    ('1', '7000'),
    ('1', '4500'),
    ('1', '1500'),
    ('1', '850'),
    ('1', '650'),
    ('0', '10000'),
    ('1', '20000'),
    ('0', '17000'),
    ('1', '11000'),
    ('1', '30000'),
    ('1', '2500'),
    ('1', '5000'),
    ('0', '5000'),
    ('0', '5000'),
]

WORK_SPECS = [
    ('1', '7000'),
    ('1', '7000'),
    ('1', '7000'),
    ('1', '13000'),
    ('1', '7000'),
    ('1', '10000'),
    ('1', '7000'),
    ('1', '7000'),
    ('1', '10000'),
    ('0', '7000'),
    ('0', '7000'),
    ('0', '7000'),
    ('0', '7000'),
    ('1', '10000'),
]


def seed_bathroom_template(apps, schema_editor):
    Section = apps.get_model('catalog', 'Section')
    CostItem = apps.get_model('catalog', 'CostItem')

    section, _ = Section.objects.get_or_create(
        code=SECTION_CODE,
        defaults={
            'name_ru': 'Шаблон наполнения санузла',
            'kind': 'bathroom_template',
            'sort_order': 0,
        },
    )

    for i, (flag, price) in enumerate(MATERIAL_SPECS, start=1):
        code = f'bath_tpl_mat_{i:02d}'
        CostItem.objects.update_or_create(
            code=code,
            defaults={
                'name_ru': f'Материал {i}',
                'unit': 'pcs',
                'category': 'bathroom',
                'price_material': Decimal(price),
                'price_work': Decimal('0'),
                'formula_multiplier': None,
                'is_active': True,
                'section_id': section.pk,
                'kind': 'material',
                'default_included': flag == '1',
                'sort_order': i,
            },
        )

    for i, (flag, price) in enumerate(WORK_SPECS, start=1):
        code = f'bath_tpl_work_{i:02d}'
        CostItem.objects.update_or_create(
            code=code,
            defaults={
                'name_ru': f'Работа {i}',
                'unit': 'pcs',
                'category': 'bathroom',
                'price_material': Decimal('0'),
                'price_work': Decimal(price),
                'formula_multiplier': None,
                'is_active': True,
                'section_id': section.pk,
                'kind': 'work',
                'default_included': flag == '1',
                'sort_order': 100 + i,
            },
        )


def unseed_bathroom_template(apps, schema_editor):
    Section = apps.get_model('catalog', 'Section')
    CostItem = apps.get_model('catalog', 'CostItem')

    CostItem.objects.filter(code__startswith='bath_tpl_mat_').delete()
    CostItem.objects.filter(code__startswith='bath_tpl_work_').delete()
    Section.objects.filter(code=SECTION_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0002_section_and_costitem_fields'),
    ]

    operations = [
        migrations.RunPython(seed_bathroom_template, unseed_bathroom_template),
    ]
