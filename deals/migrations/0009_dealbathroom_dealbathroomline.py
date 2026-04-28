# Generated manually for DealBathroom / DealBathroomLine

import django.db.models.deletion
from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0003_seed_bathroom_template'),
        ('deals', '0008_alter_projectfile_source'),
    ]

    operations = [
        migrations.CreateModel(
            name='DealBathroom',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('index', models.PositiveSmallIntegerField()),
                ('label', models.CharField(blank=True, max_length=100)),
                (
                    'deal',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='deal_bathrooms',
                        to='deals.deal',
                    ),
                ),
                (
                    'project_version',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='bathrooms',
                        to='deals.projectversion',
                    ),
                ),
            ],
            options={
                'ordering': ['index'],
            },
        ),
        migrations.CreateModel(
            name='DealBathroomLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name_snapshot', models.CharField(max_length=255)),
                (
                    'kind',
                    models.CharField(
                        choices=[('material', 'Материал'), ('work', 'Работа'), ('mixed', 'Смешанный')],
                        max_length=20,
                    ),
                ),
                ('is_included', models.BooleanField(default=True)),
                ('quantity', models.DecimalField(decimal_places=2, default=Decimal('1'), max_digits=12)),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                (
                    'bathroom',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='lines',
                        to='deals.dealbathroom',
                    ),
                ),
                (
                    'cost_item',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='deal_bathroom_lines',
                        to='catalog.costitem',
                    ),
                ),
            ],
            options={
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='dealbathroom',
            constraint=models.UniqueConstraint(fields=('project_version', 'index'), name='uniq_project_version_bathroom_index'),
        ),
    ]
