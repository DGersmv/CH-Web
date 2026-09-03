from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0025_dealapproval_hint_iscustom'),
    ]

    operations = [
        migrations.AddField(
            model_name='dealapproval',
            name='notes',
            field=models.TextField(blank=True, default='', verbose_name='Рабочие заметки по пункту'),
        ),
    ]
