from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0002_alter_task_assignee_alter_task_deal'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='attachment',
            field=models.FileField(blank=True, null=True, upload_to='task_attachments/'),
        ),
    ]
