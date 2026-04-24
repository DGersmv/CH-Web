from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_directmessage'),
    ]

    operations = [
        migrations.AddField(
            model_name='directmessage',
            name='attachment',
            field=models.FileField(blank=True, null=True, upload_to='direct_messages/'),
        ),
    ]
