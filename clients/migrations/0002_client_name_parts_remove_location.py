from django.db import migrations, models


def split_legacy_full_name(raw: str) -> dict:
    s = (raw or '').strip()
    if not s:
        return {
            'company_name': '',
            'last_name': '',
            'first_name': '',
            'middle_name': '',
        }
    upper = s.upper()
    if upper.startswith('ООО') or upper.startswith('ИП') or '«' in s or '"' in s[:24]:
        return {
            'company_name': s,
            'last_name': '',
            'first_name': '',
            'middle_name': '',
        }
    parts = s.split()
    if len(parts) == 1:
        return {
            'company_name': '',
            'last_name': parts[0],
            'first_name': '',
            'middle_name': '',
        }
    if len(parts) == 2:
        return {
            'company_name': '',
            'last_name': parts[0],
            'first_name': parts[1],
            'middle_name': '',
        }
    return {
        'company_name': '',
        'last_name': parts[0],
        'first_name': parts[1],
        'middle_name': ' '.join(parts[2:]),
    }


def forwards(apps, schema_editor):
    Client = apps.get_model('clients', 'Client')
    for c in Client.objects.iterator():
        parsed = split_legacy_full_name(getattr(c, 'full_name', '') or '')
        c.last_name = parsed['last_name']
        c.first_name = parsed['first_name']
        c.middle_name = parsed['middle_name']
        c.company_name = parsed['company_name']
        loc = (getattr(c, 'location', '') or '').strip()
        notes = (getattr(c, 'notes', '') or '').strip()
        if loc:
            prefix = f'Локация (из карточки клиента): {loc}'
            c.notes = f'{prefix}\n\n{notes}' if notes else prefix
        c.save()


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='company_name',
            field=models.CharField(blank=True, max_length=255, verbose_name='Название компании'),
        ),
        migrations.AddField(
            model_name='client',
            name='last_name',
            field=models.CharField(blank=True, max_length=100, verbose_name='Фамилия'),
        ),
        migrations.AddField(
            model_name='client',
            name='first_name',
            field=models.CharField(blank=True, max_length=100, verbose_name='Имя'),
        ),
        migrations.AddField(
            model_name='client',
            name='middle_name',
            field=models.CharField(blank=True, max_length=100, verbose_name='Отчество'),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RemoveField(model_name='client', name='full_name'),
        migrations.RemoveField(model_name='client', name='location'),
    ]
