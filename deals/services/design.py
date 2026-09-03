"""Чек-лист разделов рабочей документации по сделке (этап «Проектирование»)."""

from deals.models import DealDesignSection, ProjectVersion


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
        'slug': 'plumbing',
        'title': 'ВК',
        'hint': 'Водоснабжение и канализация: разводка, стояки, ввод/септик',
        'is_required': True,
    },
    {
        'slug': 'hvac',
        'title': 'ОВ',
        'hint': 'Отопление и вентиляция, при необходимости кондиционирование',
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


def ensure_deal_design_sections(deal):
    """Досевает недостающие разделы и синхронизирует шаблонные."""
    existing = {s.slug: s for s in deal.design_sections.all()}
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
    return list(deal.design_sections.select_related('decided_by', 'project_version').all())


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
