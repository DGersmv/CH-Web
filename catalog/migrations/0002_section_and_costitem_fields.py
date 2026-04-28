# Generated manually for Section + CostItem extensions

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Section',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=100, unique=True)),
                ('name_ru', models.CharField(max_length=255)),
                ('kind', models.CharField(choices=[('bathroom_template', 'Шаблон наполнения санузла')], max_length=40)),
                ('sort_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ('sort_order', 'code'),
            },
        ),
        migrations.AddField(
            model_name='costitem',
            name='default_included',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='costitem',
            name='kind',
            field=models.CharField(
                choices=[('material', 'Материал'), ('work', 'Работа'), ('mixed', 'Смешанный')],
                default='mixed',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='costitem',
            name='sort_order',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='costitem',
            name='section',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='items',
                to='catalog.section',
            ),
        ),
        migrations.AlterModelOptions(
            name='costitem',
            options={'ordering': ('category', 'sort_order', 'name_ru')},
        ),
    ]
