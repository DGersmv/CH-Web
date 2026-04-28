from decimal import Decimal

from django.db import migrations
from django.db.models import Max


def forwards(apps, schema_editor):
    CostItem = apps.get_model('catalog', 'CostItem')
    CostItemOption = apps.get_model('catalog', 'CostItemOption')

    materials = CostItem.objects.filter(section__code='bathroom_template_v1', kind='material')
    for ci in materials:
        max_so = CostItemOption.objects.filter(cost_item_id=ci.pk).aggregate(m=Max('sort_order'))['m'] or 0
        CostItemOption.objects.update_or_create(
            cost_item_id=ci.pk,
            code='customer_material',
            defaults={
                'name_ru': 'Материал заказчика',
                'price': Decimal('0.00'),
                'unit': ci.unit or '',
                'manufacturer': '',
                'article': '',
                'country': '',
                'description': '',
                'is_default': False,
                'is_active': True,
                'sort_order': max_so + 100,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0006_backfill_option_prices'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
