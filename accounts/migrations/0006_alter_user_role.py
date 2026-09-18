from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_notification_auditevent'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('manager', 'Manager'),
                    ('designer', 'Designer'),
                    ('production', 'Production'),
                    ('admin', 'Admin'),
                    ('head', 'Head'),
                    ('superadmin', 'Superadmin'),
                ],
                default='manager',
                max_length=20,
            ),
        ),
    ]
