# Data migration: copy unit and material price from parent CostItem into CostItemOption.

from django.db import migrations


def forwards(apps, schema_editor):
    CostItemOption = apps.get_model('catalog', 'CostItemOption')
    for opt in CostItemOption.objects.select_related('cost_item').iterator():
        ci = opt.cost_item
        if not ci:
            continue
        kind = getattr(ci, 'kind', 'mixed')
        if kind == 'work':
            price = ci.price_work
        elif kind == 'material':
            price = ci.price_material
        else:
            price = ci.price_material
        opt.price = price
        opt.unit = ci.unit or ''
        opt.save(update_fields=['price', 'unit'])


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0005_costitemoption_pricing_fields'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
