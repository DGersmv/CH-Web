from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0004_costitemoption'),
        ('deals', '0010_fill_bathroom_template_names'),
    ]

    operations = [
        migrations.AddField(
            model_name='dealbathroomline',
            name='selected_option',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='selected_bathroom_lines',
                to='catalog.costitemoption',
            ),
        ),
    ]
