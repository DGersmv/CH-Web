from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0024_dealapproval'),
    ]

    operations = [
        migrations.AddField(
            model_name='dealapproval',
            name='hint',
            field=models.CharField(blank=True, default='', max_length=300),
        ),
        migrations.AddField(
            model_name='dealapproval',
            name='is_custom',
            field=models.BooleanField(default=False),
        ),
    ]
