from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0031_servicerequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='deal',
            name='agreed_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=12,
                null=True,
                verbose_name='Договорная цена',
            ),
        ),
        migrations.AddField(
            model_name='deal',
            name='agreed_price_note',
            field=models.CharField(
                blank=True,
                max_length=300,
                verbose_name='Комментарий к цене',
            ),
        ),
        migrations.AddField(
            model_name='deal',
            name='agreed_price_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
