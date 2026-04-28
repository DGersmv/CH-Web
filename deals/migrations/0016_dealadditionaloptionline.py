from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0009_seed_additional_options_template'),
        ('deals', '0015_refresh_bathroom_line_unit_prices'),
    ]

    operations = [
        migrations.CreateModel(
            name='DealAdditionalOptionLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'name_snapshot',
                    models.CharField(max_length=255),
                ),
                (
                    'kind',
                    models.CharField(
                        choices=[('material', 'Материал'), ('work', 'Работа'), ('mixed', 'Смешанный')],
                        default='material',
                        max_length=20,
                    ),
                ),
                ('is_included', models.BooleanField(default=False)),
                ('quantity', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12)),
                ('unit_price', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                (
                    'cost_item',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='deal_additional_option_lines',
                        to='catalog.costitem',
                    ),
                ),
                (
                    'project_version',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='additional_option_lines',
                        to='deals.projectversion',
                    ),
                ),
            ],
            options={
                'ordering': ['sort_order', 'id'],
            },
        ),
    ]

