from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0003_seed_bathroom_template'),
    ]

    operations = [
        migrations.CreateModel(
            name='CostItemOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=100)),
                ('name_ru', models.CharField(max_length=255)),
                ('description', models.CharField(blank=True, max_length=500)),
                ('is_default', models.BooleanField(default=False)),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('cost_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='options', to='catalog.costitem')),
            ],
            options={
                'ordering': ('sort_order', 'name_ru'),
            },
        ),
        migrations.AddConstraint(
            model_name='costitemoption',
            constraint=models.UniqueConstraint(fields=('cost_item', 'code'), name='uniq_cost_item_option_code'),
        ),
    ]
