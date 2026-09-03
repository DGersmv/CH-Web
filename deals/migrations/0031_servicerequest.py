from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0030_telegram_bot'),
        ('clients', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.PositiveIntegerField(editable=False, unique=True, verbose_name='Номер')),
                (
                    'kind',
                    models.CharField(
                        choices=[
                            ('reclamation', 'Рекламация (гарантия)'),
                            ('service', 'Сервис / доработка'),
                            ('question', 'Вопрос / обращение'),
                        ],
                        default='service',
                        max_length=20,
                        verbose_name='Тип',
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('new', 'Новая'),
                            ('in_progress', 'В работе'),
                            ('waiting', 'Ожидание (клиент / поставщик)'),
                            ('done', 'Закрыта'),
                            ('rejected', 'Отклонена'),
                        ],
                        default='new',
                        max_length=20,
                        verbose_name='Статус',
                    ),
                ),
                (
                    'priority',
                    models.CharField(
                        choices=[
                            ('low', 'Низкий'),
                            ('normal', 'Обычный'),
                            ('high', 'Высокий'),
                            ('urgent', 'Срочно'),
                        ],
                        default='normal',
                        max_length=20,
                        verbose_name='Приоритет',
                    ),
                ),
                (
                    'source',
                    models.CharField(
                        choices=[
                            ('phone', 'Телефон'),
                            ('telegram', 'Telegram'),
                            ('email', 'E-mail'),
                            ('portal', 'Портал клиента'),
                            ('other', 'Другое'),
                        ],
                        default='phone',
                        max_length=20,
                        verbose_name='Откуда обращение',
                    ),
                ),
                ('title', models.CharField(max_length=200, verbose_name='Суть обращения')),
                ('description', models.TextField(blank=True, default='', verbose_name='Подробности')),
                ('reporter_name', models.CharField(blank=True, default='', max_length=150, verbose_name='Кто обратился')),
                ('reporter_phone', models.CharField(blank=True, default='', max_length=50, verbose_name='Контактный телефон')),
                ('resolution', models.TextField(blank=True, default='', verbose_name='Что сделали / итог')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                (
                    'assignee',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='service_requests',
                        to=settings.AUTH_USER_MODEL,
                        verbose_name='Ответственный',
                    ),
                ),
                (
                    'client',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='service_requests',
                        to='clients.client',
                        verbose_name='Клиент',
                    ),
                ),
                (
                    'created_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='created_service_requests',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'deal',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='service_requests',
                        to='deals.deal',
                        verbose_name='Сделка / объект',
                    ),
                ),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ServiceRequestEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'kind',
                    models.CharField(
                        choices=[
                            ('comment', 'Комментарий'),
                            ('status', 'Смена статуса'),
                            ('system', 'Система'),
                        ],
                        default='comment',
                        max_length=20,
                    ),
                ),
                ('text', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'author',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='service_request_events',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'request',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='events',
                        to='deals.servicerequest',
                    ),
                ),
            ],
            options={
                'ordering': ['created_at', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='servicerequest',
            index=models.Index(fields=['status', '-created_at'], name='service_req_status_idx'),
        ),
        migrations.AddIndex(
            model_name='servicerequest',
            index=models.Index(fields=['kind', 'status'], name='service_req_kind_status_idx'),
        ),
    ]
