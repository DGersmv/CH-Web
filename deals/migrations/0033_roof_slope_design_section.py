"""Раздел «Разуклонка» + вложение PDF из чата в сделку 6МД-Ирина-Раздолье."""

import mimetypes
import shutil

from django.conf import settings
from django.db import migrations

from deals.services.storage_paths import slugify_safe

SLUG = 'roof_slope'
TITLE = 'Разуклонка'
HINT = 'Разуклонка кровли: уклоны, воронки, водоотвод; если скатная — «Не требуется»'

DEAL_CODE = '6МД-Ирина-Раздолье'
CHAT_DIR = 'umnik_chat/20'
CHAT_GLOB = '*разуклонка*.pdf'
ORIGINAL_NAME = 'разуклонка кровли.pdf'


def _client_label(client):
    """Повторяет Client.full_name: у исторических моделей свойств нет."""
    if client is None:
        return ''
    company = (client.company_name or '').strip()
    if company:
        return company
    parts = [
        (client.last_name or '').strip(),
        (client.first_name or '').strip(),
        (client.middle_name or '').strip(),
    ]
    return ' '.join(part for part in parts if part).strip()


def _deal_root(files_root, deal):
    """Аналог get_deal_root на полях модели, без обращения к @property."""
    client = deal.client if deal.client_id else None
    if client is None:
        client_dir = 'client-unknown'
    else:
        client_dir = f'{client.id}-{slugify_safe(_client_label(client), "client")}'
    deal_dir = f'{deal.id}-{slugify_safe(deal.project_code, "project")}'
    return files_root / 'clients' / client_dir / 'projects' / deal_dir


def forwards(apps, schema_editor):
    Deal = apps.get_model('deals', 'Deal')
    DealDesignSection = apps.get_model('deals', 'DealDesignSection')
    ProjectFile = apps.get_model('deals', 'ProjectFile')

    deal = Deal.objects.filter(project_code=DEAL_CODE).first()
    if deal is None:
        return

    # Раздел досевается и лениво (ensure_deal_design_sections), но файл нужен уже сейчас.
    after = deal.design_sections.filter(slug='kr_ceiling').values_list('sort_order', flat=True).first()
    section, _ = DealDesignSection.objects.get_or_create(
        deal=deal,
        slug=SLUG,
        defaults={
            'title': TITLE,
            'hint': HINT,
            'is_required': False,
            'sort_order': (after or 4) + 1,
        },
    )

    if ProjectFile.objects.filter(deal=deal, design_section=section).exists():
        return

    files_root = settings.CRM_FILES_ROOT
    # Человек мог перезалить файл в чат — берём самую свежую копию, имя не фиксируем.
    candidates = sorted((files_root / CHAT_DIR).glob(CHAT_GLOB))
    if not candidates:
        return
    source = candidates[-1]

    target_name = source.name.replace('__', '_')
    relative_path = _deal_root(files_root, deal).joinpath('design', SLUG, target_name).relative_to(files_root)
    absolute_path = files_root / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    if not absolute_path.exists():
        shutil.copy2(source, absolute_path)

    ProjectFile.objects.create(
        deal=deal,
        design_section=section,
        project_version=section.project_version,
        source='system',
        category='pdf',
        relative_path=str(relative_path).replace('\\', '/'),
        original_name=ORIGINAL_NAME,
        size_bytes=absolute_path.stat().st_size,
        mime_type=mimetypes.guess_type(ORIGINAL_NAME)[0] or 'application/pdf',
        ext='pdf',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0032_deal_agreed_price'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
