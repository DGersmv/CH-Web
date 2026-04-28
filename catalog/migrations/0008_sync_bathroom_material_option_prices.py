"""Options created in deals.0012_seed_bathroom_options had no price set (default 0).

catalog.0006_backfill_option_prices ran before those rows existed. Sync non-customer
material options from CostItem.price_material so bathrooms_totals matches legacy sheet.
"""

from decimal import Decimal

from django.db import migrations


def forwards(apps, schema_editor):
    CostItemOption = apps.get_model('catalog', 'CostItemOption')

    qs = CostItemOption.objects.filter(
        cost_item__section__code='bathroom_template_v1',
        cost_item__kind='material',
    ).exclude(code='customer_material')

    for opt in qs.select_related('cost_item').iterator():
        ci = opt.cost_item
        if ci is None:
            continue
        if opt.price != Decimal('0'):
            continue
        opt.price = ci.price_material
        opt.save(update_fields=['price'])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0007_seed_customer_material_option'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
