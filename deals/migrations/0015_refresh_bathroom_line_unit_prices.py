"""After catalog.0008 fixes CostItemOption.price, refresh cached unit_price on bathroom lines."""

from decimal import Decimal

from django.db import migrations


def forwards(apps, schema_editor):
    DealBathroomLine = apps.get_model('deals', 'DealBathroomLine')

    qs = (
        DealBathroomLine.objects.filter(kind='material')
        .exclude(selected_option__isnull=True)
        .exclude(selected_option__code='customer_material')
        .select_related('selected_option', 'cost_item')
    )

    for line in qs.iterator():
        opt = line.selected_option
        ci = line.cost_item
        new_price = opt.price
        if new_price == Decimal('0') and ci is not None:
            new_price = ci.price_material
        if line.unit_price != new_price:
            line.unit_price = new_price
            line.save(update_fields=['unit_price'])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0008_sync_bathroom_material_option_prices'),
        ('deals', '0014_backfill_default_selected_option'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
