from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0028_dealdesignsection'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UmnikChatAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('origin', models.CharField(choices=[('upload', 'Загружен в чат'), ('server', 'Взят с сервера'), ('umnik', 'Добавил умник')], default='upload', max_length=16)),
                ('relative_path', models.CharField(max_length=500)),
                ('original_name', models.CharField(max_length=255)),
                ('mime_type', models.CharField(blank=True, default='', max_length=150)),
                ('size_bytes', models.PositiveBigIntegerField(default=0)),
                ('source_path', models.CharField(blank=True, default='', max_length=600)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='deals.umnikchatmessage')),
                ('thread', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='deals.umnikchatthread')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='umnik_chat_attachments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='umnikchatattachment',
            index=models.Index(fields=['thread', 'message', 'created_at'], name='umnik_attach_thread_idx'),
        ),
    ]
