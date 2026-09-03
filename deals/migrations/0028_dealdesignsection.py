from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('deals', '0027_projectfile_approval'),
    ]

    operations = [
        migrations.AddField(
            model_name='deal',
            name='design_passed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Проектирование завершено'),
        ),
        migrations.CreateModel(
            name='DealDesignSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=50)),
                ('title', models.CharField(max_length=200)),
                ('hint', models.CharField(blank=True, default='', max_length=300)),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('not_started', 'Не начато'),
                            ('in_progress', 'В работе'),
                            ('review', 'На проверке'),
                            ('released', 'Выпущен'),
                            ('on_hold', 'Отложен'),
                            ('not_required', 'Не требуется'),
                        ],
                        default='not_started',
                        max_length=20,
                    ),
                ),
                ('is_required', models.BooleanField(default=True)),
                ('is_custom', models.BooleanField(default=False)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('comment', models.TextField(blank=True, default='')),
                ('notes', models.TextField(blank=True, default='', verbose_name='Рабочие заметки по разделу')),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'deal',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='design_sections',
                        to='deals.deal',
                    ),
                ),
                (
                    'decided_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='decided_deal_design_sections',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'project_version',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='design_sections',
                        to='deals.projectversion',
                    ),
                ),
            ],
            options={
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.AddField(
            model_name='projectfile',
            name='design_section',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='files',
                to='deals.dealdesignsection',
            ),
        ),
        migrations.AddConstraint(
            model_name='dealdesignsection',
            constraint=models.UniqueConstraint(fields=('deal', 'slug'), name='uniq_deal_design_section_slug'),
        ),
    ]
