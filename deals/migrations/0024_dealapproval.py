from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('deals', '0023_umnik_chat_threads'),
    ]

    operations = [
        migrations.AddField(
            model_name='deal',
            name='approvals_passed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Согласования пройдены'),
        ),
        migrations.CreateModel(
            name='DealApproval',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=50)),
                ('title', models.CharField(max_length=200)),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('not_started', 'Не начато'),
                            ('waiting_client', 'Ждём клиента'),
                            ('approved', 'Согласовано'),
                            ('rejected', 'Отклонено'),
                            ('not_required', 'Не требуется'),
                        ],
                        default='not_started',
                        max_length=20,
                    ),
                ),
                ('is_required', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('comment', models.TextField(blank=True, default='')),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'deal',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='approvals',
                        to='deals.deal',
                    ),
                ),
                (
                    'decided_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='decided_deal_approvals',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'project_version',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='approvals',
                        to='deals.projectversion',
                    ),
                ),
            ],
            options={
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='dealapproval',
            constraint=models.UniqueConstraint(fields=('deal', 'slug'), name='uniq_deal_approval_slug'),
        ),
    ]
