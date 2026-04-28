from django.db import migrations


def forwards(apps, schema_editor):
    DealBathroomLine = apps.get_model('deals', 'DealBathroomLine')
    CostItemOption = apps.get_model('catalog', 'CostItemOption')

    qs = (
        DealBathroomLine.objects.filter(kind='material', selected_option__isnull=True)
        .select_related('cost_item')
        .iterator()
    )
    for line in qs:
        if not line.cost_item_id:
            continue
        opt = (
            CostItemOption.objects.filter(cost_item_id=line.cost_item_id, is_active=True)
            .exclude(code='customer_material')
            .order_by('sort_order', 'id')
            .first()
        )
        if not opt:
            continue
        line.selected_option_id = opt.pk
        line.unit_price = opt.price
        line.save(update_fields=['selected_option_id', 'unit_price'])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0007_seed_customer_material_option'),
        ('deals', '0013_normalize_bathroom_template_item_names'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
