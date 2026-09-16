"""Чек-лист разделов рабочей документации по сделке (этап «Проектирование»)."""

from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path

from django.utils import timezone

from deals.models import DealDesignSection, ProjectFile, ProjectVersion, UmnikChatAttachment
from deals.services.storage_paths import ensure_deal_dirs, get_deal_root, get_files_root, slugify_safe

OV_VK_SLUG = 'ov_vk'
LEGACY_OV_VK_SLUGS = ('plumbing', 'hvac')
_STATUS_PROGRESS = {
    DealDesignSection.Status.NOT_STARTED: 0,
    DealDesignSection.Status.ON_HOLD: 1,
    DealDesignSection.Status.IN_PROGRESS: 2,
    DealDesignSection.Status.REVIEW: 3,
    DealDesignSection.Status.RELEASED: 4,
}


DEFAULT_DESIGN_SECTIONS = [
    {
        'slug': 'layout',
        'title': 'Планировка',
        'hint': 'Финальная планировка под принятую версию: разрезы, узлы, высоты',
        'is_required': True,
    },
    {
        'slug': 'facades',
        'title': 'Фасады',
        'hint': 'Фасады со всех сторон + ведомость отделки фасада',
        'is_required': True,
    },
    {
        'slug': 'kr_floor',
        'title': 'КР-ПОЛ',
        'hint': 'Конструктив пола: балки, пирог, спецификация',
        'is_required': True,
    },
    {
        'slug': 'kr_walls',
        'title': 'КР-СТЕНЫ',
        'hint': 'Конструктив стен: каркас, стойки, узлы, спецификация',
        'is_required': True,
    },
    {
        'slug': 'kr_ceiling',
        'title': 'КР-ПОТОЛОК',
        'hint': 'Конструктив потолка/кровли: балки, стропилка, пирог',
        'is_required': True,
    },
    {
        'slug': 'roof_slope',
        'title': 'Разуклонка',
        'hint': 'Разуклонка кровли: уклоны, воронки, водоотвод; если скатная — «Не требуется»',
        'is_required': False,
    },
    {
        'slug': 'cassettes',
        'title': 'Кассеты',
        'hint': 'Раскладка стеновых и потолочных кассет по модулям',
        'is_required': True,
    },
    {
        'slug': 'module_dimensions',
        'title': 'Размеры модулей',
        'hint': 'Габариты модулей, границы, стыки, монтажная схема',
        'is_required': True,
    },
    {
        'slug': 'openings',
        'title': 'Окна / двери',
        'hint': 'Ведомость окон и дверей, заполнение проёмов, заказные позиции',
        'is_required': True,
    },
    {
        'slug': 'electrical',
        'title': 'Электрика',
        'hint': 'ЭОМ: щит, розетки/выключатели, слаботочка, ввод и мощность',
        'is_required': True,
    },
    {
        'slug': OV_VK_SLUG,
        'title': 'ОВ / ВК',
        'hint': 'Отопление, вентиляция, водоснабжение и канализация',
        'is_required': True,
    },
    {
        'slug': 'finishing',
        'title': 'Отделка',
        'hint': 'Ведомость чистовой отделки помещений: полы, стены, потолки',
        'is_required': True,
    },
    {
        'slug': 'foundation',
        'title': 'Фундамент',
        'hint': 'Тип и расчёт по геологии, посадка на участок, отметки',
        'is_required': True,
    },
    {
        'slug': 'canopies',
        'title': 'Навесы/Террасы',
        'hint': 'Конструктив навесов и террас; если нет — отметить «Не требуется»',
        'is_required': False,
    },
    {
        'slug': 'spec',
        'title': 'Спецификации',
        'hint': 'Сводная ведомость материалов и комплектующих для закупа и цеха',
        'is_required': True,
    },
    {
        'slug': 'low_voltage',
        'title': 'Слаботочка',
        'hint': 'Интернет, видеонаблюдение, сигнализация, автоматика умного дома',
        'is_required': False,
    },
    {
        'slug': 'stairs',
        'title': 'Лестница',
        'hint': 'Только для двухэтажных домов: конструктив и узлы лестницы',
        'is_required': False,
    },
]

DEFAULT_DESIGN_SECTION_BY_SLUG = {item['slug']: item for item in DEFAULT_DESIGN_SECTIONS}


def _join_section_text(*parts):
    seen = set()
    chunks = []
    for part in parts:
        text = (part or '').strip()
        if text and text not in seen:
            seen.add(text)
            chunks.append(text)
    return '\n\n'.join(chunks)


def _merged_ov_vk_status(sections):
    statuses = [section.status for section in sections]
    if statuses and all(status == DealDesignSection.Status.NOT_REQUIRED for status in statuses):
        return DealDesignSection.Status.NOT_REQUIRED
    active = [status for status in statuses if status != DealDesignSection.Status.NOT_REQUIRED]
    if not active:
        return DealDesignSection.Status.NOT_STARTED
    return min(active, key=lambda status: _STATUS_PROGRESS.get(status, 0))


def _merge_legacy_ov_vk_sections(existing):
    """Склеивает старые разделы ВК и ОВ в один «ОВ / ВК», переносит файлы и заметки."""
    legacy = [existing[slug] for slug in LEGACY_OV_VK_SLUGS if slug in existing]
    if not legacy:
        return existing

    target = existing.get(OV_VK_SLUG)
    if target is None:
        target = legacy[0]
        target.slug = OV_VK_SLUG
        target.is_custom = False

    sources = [section for section in legacy if section.pk != target.pk]
    merge_from = [target, *sources]
    target.title = DEFAULT_DESIGN_SECTION_BY_SLUG[OV_VK_SLUG]['title']
    target.hint = DEFAULT_DESIGN_SECTION_BY_SLUG[OV_VK_SLUG]['hint']
    target.is_required = any(section.is_required for section in merge_from)
    target.status = _merged_ov_vk_status(merge_from)
    target.comment = _join_section_text(*(section.comment for section in merge_from))
    target.notes = _join_section_text(*(section.notes for section in merge_from))
    target.project_version = next(
        (section.project_version for section in merge_from if section.project_version_id),
        None,
    )
    decided = [section for section in merge_from if section.decided_at]
    if decided:
        latest = max(decided, key=lambda section: section.decided_at)
        target.decided_by = latest.decided_by
        target.decided_at = latest.decided_at
    target.save()

    if sources:
        ProjectFile.objects.filter(design_section__in=sources).update(design_section=target)
        DealDesignSection.objects.filter(pk__in=[section.pk for section in sources]).delete()

    for slug in LEGACY_OV_VK_SLUGS:
        existing.pop(slug, None)
    existing[OV_VK_SLUG] = target
    return existing


def ensure_deal_design_sections(deal):
    """Досевает недостающие разделы и синхронизирует шаблонные."""
    existing = _merge_legacy_ov_vk_sections(
        {s.slug: s for s in deal.design_sections.all()},
    )
    to_create = []
    to_update = []
    for index, item in enumerate(DEFAULT_DESIGN_SECTIONS):
        current = existing.get(item['slug'])
        if current is None:
            to_create.append(
                DealDesignSection(
                    deal=deal,
                    slug=item['slug'],
                    title=item['title'],
                    hint=item['hint'],
                    is_required=item['is_required'],
                    sort_order=index,
                )
            )
            continue
        if not current.is_custom:
            changed = False
            if current.title != item['title']:
                current.title = item['title']
                changed = True
            if current.hint != item['hint']:
                current.hint = item['hint']
                changed = True
            if current.sort_order != index:
                current.sort_order = index
                changed = True
            if changed:
                to_update.append(current)
    if to_create:
        DealDesignSection.objects.bulk_create(to_create)
    if to_update:
        DealDesignSection.objects.bulk_update(to_update, ['title', 'hint', 'sort_order'])
    return list(
        deal.design_sections.select_related('decided_by', 'project_version').order_by(
            'sort_order',
            'id',
        )
    )


def design_gate(items):
    """Сводка по гейту этапа «Проектирование»."""
    required = [i for i in items if i.is_required]
    blocking = [i for i in required if not i.is_satisfied]
    return {
        'required_total': len(required),
        'required_satisfied': len(required) - len(blocking),
        'blocking': blocking,
        'passed': not blocking,
    }


def build_design_context(deal):
    """Общий контекст для карточки сделки и htmx-партиала чек-листа разделов."""
    items = ensure_deal_design_sections(deal)
    from deals.models import DealInstruction
    from deals.services.instructions import attach_latest_instructions

    attach_latest_instructions(deal, items, DealInstruction.Kind.DESIGN)
    versions = list(
        ProjectVersion.objects.filter(deal=deal)
        .select_related('created_by')
        .order_by('-version_number')
    )
    return {
        'deal': deal,
        'design_sections_list': items,
        'design_gate': design_gate(items),
        'design_versions': versions,
        'design_status_choices': DealDesignSection.Status.choices,
    }


def _normalize_upload_name(filename: str) -> str:
    safe = ''.join(ch for ch in filename if ch not in '/\\').strip()
    return safe or 'file.bin'


def _detect_category(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in {'.jpg', '.jpeg', '.png', '.webp', '.gif'}:
        return ProjectFile.Category.PHOTO
    if ext == '.pdf':
        return ProjectFile.Category.PDF
    if ext in {'.dwg', '.dxf'}:
        return ProjectFile.Category.DWG
    return ProjectFile.Category.OTHER


def _resolve_source_path(raw: str) -> Path | None:
    """Путь с хоста или из контейнера → существующий файл."""
    text = (raw or '').strip().strip('"')
    if not text:
        return None
    try:
        direct = Path(text)
        if direct.is_file():
            return direct
    except OSError:
        pass
    from deals.services.umnik_chat import resolve_server_path

    mapped = resolve_server_path(text)
    if mapped is not None and mapped.is_file():
        return mapped
    rel = text.replace('\\', '/').lstrip('/')
    files_root = get_files_root()
    for prefix in ('crm_files/',):
        if rel.lower().startswith(prefix):
            rel = rel[len(prefix) :]
    candidate = files_root / rel
    if candidate.is_file():
        return candidate
    marker = 'umnik_chat/'
    idx = rel.lower().find(marker)
    if idx >= 0:
        candidate = files_root / rel[idx:]
        if candidate.is_file():
            return candidate
    return None


def get_or_create_design_section(deal, slug: str, title: str = ''):
    """Находит раздел на сделке или создаёт его (шаблонный или кастомный)."""
    ensure_deal_design_sections(deal)
    slug = (slug or '').strip()
    title = (title or '').strip()
    if not slug and title:
        slug = slugify_safe(title, 'section')
    if not slug:
        return None, 'slug_required'
    slug = slug[:50]
    existing = deal.design_sections.filter(slug=slug).first()
    if existing is not None:
        return existing, None
    template = next((item for item in DEFAULT_DESIGN_SECTIONS if item['slug'] == slug), None)
    if template is not None:
        section = DealDesignSection.objects.create(
            deal=deal,
            slug=template['slug'],
            title=template['title'],
            hint=template['hint'],
            is_required=template['is_required'],
            sort_order=len(DEFAULT_DESIGN_SECTIONS),
        )
        return section, None
    section = DealDesignSection.objects.create(
        deal=deal,
        slug=slug,
        title=title or slug,
        hint='',
        is_required=False,
        is_custom=True,
        sort_order=deal.design_sections.count(),
    )
    return section, None


def attach_file_to_design_section(
    deal,
    *,
    slug: str,
    source_path: str = '',
    attachment_id=None,
    title: str = '',
    user=None,
):
    """Копирует файл в design/<slug>/ и пишет ProjectFile. Повтор с тем же именем — без дубля."""
    original_name = ''
    source = None
    if attachment_id not in (None, ''):
        try:
            att = UmnikChatAttachment.objects.filter(pk=int(attachment_id)).first()
        except (TypeError, ValueError):
            att = None
        if att is None:
            return {'ok': False, 'error': 'attachment not found'}
        source = att.absolute_path
        original_name = att.original_name
        if not source.exists() or not source.is_file():
            return {'ok': False, 'error': 'attachment file missing'}
    else:
        source = _resolve_source_path(source_path)
        if source is None:
            return {'ok': False, 'error': 'source file not found'}
        original_name = source.name

    section, err = get_or_create_design_section(deal, slug, title)
    if err:
        return {'ok': False, 'error': err}

    original_name = _normalize_upload_name(original_name)
    existing = (
        ProjectFile.objects.filter(
            deal=deal,
            design_section=section,
            original_name=original_name,
            is_archived=False,
        )
        .order_by('id')
        .first()
    )
    if existing is not None:
        abs_existing = get_files_root() / existing.relative_path
        if abs_existing.is_file():
            from deals.models import DealInstruction
            from deals.services.instructions import record_instruction

            record_instruction(
                deal=deal,
                user=user,
                text=original_name,
                kind=DealInstruction.Kind.DESIGN,
                source=DealInstruction.Source.CHAT,
                design_section=section,
            )
            return {
                'ok': True,
                'reused': True,
                'section': {'id': section.id, 'slug': section.slug, 'title': section.title},
                'file': {
                    'id': existing.id,
                    'original_name': existing.original_name,
                    'relative_path': existing.relative_path,
                    'size_bytes': existing.size_bytes,
                },
            }

    ensure_deal_dirs(deal)
    category = _detect_category(original_name)
    ext = Path(original_name).suffix.lower().lstrip('.')
    stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    dest = get_deal_root(deal) / 'design' / section.slug / f'{stamp}_{original_name}'
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    relative_path = str(dest.relative_to(get_files_root())).replace('\\', '/')
    created = ProjectFile.objects.create(
        deal=deal,
        design_section=section,
        project_version=section.project_version,
        source=ProjectFile.Source.SYSTEM,
        category=category,
        relative_path=relative_path,
        original_name=original_name,
        size_bytes=dest.stat().st_size,
        mime_type=mimetypes.guess_type(original_name)[0] or '',
        ext=ext,
        uploaded_by=user if getattr(user, 'pk', None) else None,
    )
    if user is not None:
        from system_settings.events import record_domain_event
        from deals.models import DealInstruction
        from deals.services.instructions import record_instruction

        record_domain_event(
            actor=user,
            event_type='deal.design_file_added',
            entity_model='DealDesignSection',
            entity_id=section.id,
            payload={
                'deal_id': deal.id,
                'slug': section.slug,
                'file_id': created.id,
                'name': original_name,
            },
        )
        record_instruction(
            deal=deal,
            user=user,
            text=original_name,
            kind=DealInstruction.Kind.DESIGN,
            source=DealInstruction.Source.CHAT,
            design_section=section,
        )
    return {
        'ok': True,
        'reused': False,
        'section': {'id': section.id, 'slug': section.slug, 'title': section.title},
        'file': {
            'id': created.id,
            'original_name': created.original_name,
            'relative_path': created.relative_path,
            'size_bytes': created.size_bytes,
        },
    }
