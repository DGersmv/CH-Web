import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0008_alter_projectfile_source'),
        ('tasks', '0003_task_attachment'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='project_file',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tasks', to='deals.projectfile'),
        ),
    ]
