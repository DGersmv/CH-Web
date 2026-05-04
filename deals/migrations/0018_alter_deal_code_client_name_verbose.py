from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0017_dealadditionaloptionline_unit_snapshot'),
    ]

    operations = [
        migrations.AlterField(
            model_name='deal',
            name='code_client_name',
            field=models.CharField(
                blank=True,
                max_length=200,
                verbose_name='Имя / компания (в коде проекта)',
            ),
        ),
    ]
