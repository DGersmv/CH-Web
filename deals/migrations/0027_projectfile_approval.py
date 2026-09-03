from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0026_dealapproval_notes'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectfile',
            name='approval',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='files',
                to='deals.dealapproval',
            ),
        ),
    ]
