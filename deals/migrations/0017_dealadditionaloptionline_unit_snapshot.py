from django.db import migrations, models


def forwards(apps, schema_editor):
    DealAdditionalOptionLine = apps.get_model('deals', 'DealAdditionalOptionLine')
    for line in DealAdditionalOptionLine.objects.select_related('cost_item').iterator():
        unit = getattr(line.cost_item, 'unit', '') if line.cost_item_id else ''
        line.unit_snapshot = unit or 'pcs'
        line.save(update_fields=['unit_snapshot'])


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0016_dealadditionaloptionline'),
    ]

    operations = [
        migrations.AddField(
            model_name='dealadditionaloptionline',
            name='unit_snapshot',
            field=models.CharField(blank=True, default='pcs', max_length=20),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

