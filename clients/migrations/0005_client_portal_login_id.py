from django.db import migrations, models


PORTAL_LOGIN_ID_BASE = 100000


def fill_portal_login_ids(apps, schema_editor):
    Client = apps.get_model('clients', 'Client')
    used = set()
    for client in Client.objects.order_by('pk'):
        candidate = str(PORTAL_LOGIN_ID_BASE + int(client.pk))
        while candidate in used:
            candidate = str(int(candidate) + 1)
        client.portal_login_id = candidate
        client.save(update_fields=['portal_login_id'])
        used.add(candidate)


def clear_portal_login_ids(apps, schema_editor):
    Client = apps.get_model('clients', 'Client')
    Client.objects.all().update(portal_login_id='')


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0004_client_portal_password_hash'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='portal_login_id',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Отдельный номер для кабинета, не внутренний № карточки.',
                max_length=12,
                verbose_name='ID для входа',
            ),
        ),
        migrations.RunPython(fill_portal_login_ids, clear_portal_login_ids),
        migrations.AlterField(
            model_name='client',
            name='portal_login_id',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Отдельный номер для кабинета, не внутренний № карточки.',
                max_length=12,
                unique=True,
                verbose_name='ID для входа',
            ),
        ),
    ]
